"""Approval workflow (M7): the structural gate for customer-facing communication.

Principle 10: no customer-facing item is ever sent without explicit human
approval. The ONLY send path is send_customer_message(), and it raises
ApprovalRequired unless the approval row is 'approved'. Internal actions
(scans, tasks, reports, and the drafts themselves) never require approval.

Decisions are recorded on the approval row (decided_by/decided_at/status) AND
in the append-only app.decision log (kind 'approval'/'rejection', M10) — "show
the decision on the platform".
"""

import datetime
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.approvals.models import Approval
from valeri_api.approvals.schemas import DraftMessage
from valeri_api.audit.decision import log_decision
from valeri_api.audit.serialization import jsonable
from valeri_api.config import get_settings
from valeri_api.llm.client import LLMClient
from valeri_api.llm.masking import build_masked_payload, rehydrate
from valeri_api.llm.prompts import MESSAGE_SYSTEM_PROMPT
from valeri_api.llm.schemas import NarrationFailed
from valeri_api.llm.structured import narrate_structured

logger = logging.getLogger("valeri.approvals.workflow")

# Tasks from these rules are the customer-facing win-back candidates (D3).
DRAFT_RULES = ("customer_decline", "sleeping_customer")


class ApprovalRequired(Exception):
    """A customer-facing send was attempted without an approved approval row."""


class InvalidTransition(Exception):
    """A lifecycle transition the approval workflow does not allow."""


# ── lifecycle ─────────────────────────────────────────────────────────────────


def _get(session: Session, approval_id: int) -> Approval:
    approval = session.get(Approval, approval_id)
    if approval is None:
        raise LookupError(f"Approval {approval_id} not found")
    return approval


def create_draft(
    session: Session, task_id: int | None, kind: str, payload: dict[str, Any]
) -> Approval:
    """Create a customer-facing draft. Born unapproved; can never auto-send."""
    approval = Approval(task_id=task_id, kind=kind, status="draft", payload=jsonable(payload))
    session.add(approval)
    session.flush()
    return approval


def submit_for_approval(session: Session, approval_id: int) -> Approval:
    """draft → pending_approval (the draft enters the owner's approval queue)."""
    approval = _get(session, approval_id)
    if approval.status != "draft":
        raise InvalidTransition(
            f"Approval {approval_id} is {approval.status!r}; only drafts can be submitted"
        )
    approval.status = "pending_approval"
    session.flush()
    return approval


def decide(
    session: Session,
    approval_id: int,
    decision: str,
    decided_by: int | None = None,
    note: str | None = None,
) -> Approval:
    """pending_approval → approved / rejected; 'deferred' keeps it pending.

    Records who decided and when on the approval row itself.
    """
    approval = _get(session, approval_id)
    if approval.status != "pending_approval":
        raise InvalidTransition(
            f"Approval {approval_id} is {approval.status!r}; only pending approvals can be decided"
        )
    if decision == "deferred":
        return approval
    if decision not in ("approved", "rejected"):
        raise InvalidTransition(f"Unknown decision {decision!r}")

    approval.status = decision
    approval.decided_by = decided_by
    approval.decided_at = datetime.datetime.now(datetime.UTC)
    if note:
        approval.payload = {**(approval.payload or {}), "decision_note": note}

    # M10: the human gate is also an append-only app.decision. It is marked
    # irreversible by design — it IS the explicit human confirmation (principle 10);
    # there is no un-approve transition.
    log_decision(
        session,
        kind="approval" if decision == "approved" else "rejection",
        actor="user",
        summary=(
            f"Odobrenje #{approval_id} ({approval.kind}): "
            + ("odobreno" if decision == "approved" else "odbijeno")
        ),
        payload={
            "approval_id": approval_id,
            "task_id": approval.task_id,
            "kind": approval.kind,
            "decided_by": decided_by,
            "note": note,
        },
        reversible=False,
    )
    session.flush()
    return approval


def send_customer_message(session: Session, approval_id: int) -> Approval:
    """THE GATE (principle 10): the only send path for customer-facing messages.

    Raises ApprovalRequired unless the approval row is 'approved'. In M7 "send"
    is the gated state transition approved → sent; the real transport
    (e-mail/SMS/Viber) is a Phase-2/pilot integration behind this same gate.
    """
    approval = _get(session, approval_id)
    if approval.status != "approved":
        raise ApprovalRequired(
            f"Approval {approval_id} is {approval.status!r}, not 'approved' — "
            "customer-facing messages cannot be sent without explicit human approval"
        )
    approval.status = "sent"
    approval.payload = {
        **(approval.payload or {}),
        "sent_at": datetime.datetime.now(datetime.UTC).isoformat(),
    }
    session.flush()
    return approval


# ── draft generation (runs during weekly report generation) ──────────────────

_DRAFT_CANDIDATES_SQL = """
SELECT t.id        AS task_id,
       s.id        AS signal_id,
       s.rule,
       s.customer_id,
       c.name      AS customer_name,
       c.segment,
       s.evidence
FROM app.task t
JOIN app.signal s ON s.id = t.signal_id
JOIN core.customer c ON c.id = s.customer_id
WHERE s.rule = ANY(:rules)
  AND t.created_at::date BETWEEN :week_start AND :week_end
  AND t.status = 'open'
  AND NOT EXISTS (
      SELECT 1 FROM app.approval a WHERE a.task_id = t.id AND a.kind = 'message'
  )
ORDER BY t.id
"""


def generate_customer_drafts(
    session: Session,
    week_start: datetime.date,
    week_end: datetime.date,
    client: LLMClient | None = None,
) -> list[Approval]:
    """Draft win-back messages for this week's decline + sleeping tasks (D3).

    Drafts are LLM-written (masked, number-contract-checked) with a deterministic
    template fallback, attached to their task, and submitted for approval.
    Nothing here sends anything — sending requires send_customer_message() on an
    approved row.
    """
    rows = (
        session.execute(
            text(_DRAFT_CANDIDATES_SQL),
            {"rules": list(DRAFT_RULES), "week_start": week_start, "week_end": week_end},
        )
        .mappings()
        .all()
    )
    narration_active = client is not None or get_settings().llm_narration_enabled

    approvals: list[Approval] = []
    for row in rows:
        message, source = _draft_message(session, dict(row), narration_active, client)
        approval = create_draft(
            session,
            task_id=row["task_id"],
            kind="message",
            payload={
                "message": message,
                "customer_name": row["customer_name"],
                "rule": row["rule"],
                "channel": "message",
                "source": source,
                "register": "akcija",
            },
        )
        submit_for_approval(session, approval.id)
        approvals.append(approval)
    return approvals


def _draft_message(
    session: Session,
    row: dict[str, Any],
    narration_active: bool,
    client: LLMClient | None,
) -> tuple[str, str]:
    """One win-back message: LLM through the M6 discipline, template fallback."""
    if narration_active:
        masked_payload, context = build_masked_payload(
            rule=row["rule"],
            evidence=row["evidence"],
            customer_id=row["customer_id"],
            customer_name=row["customer_name"],
            segment=row["segment"],
        )
        try:
            draft, _, _ = narrate_structured(
                session,
                masked_payload,
                DraftMessage,
                system_prompt=MESSAGE_SYSTEM_PROMPT,
                instruction=(
                    "Napiši prijedlog poruke kupcu (win-back) na osnovu datog signala "
                    "otkrivenog SQL analizom prodajnih podataka."
                ),
                client=client,
                register="akcija",
                role="customer_draft",  # M12: Tier-1 by role
            )
            # Drafts are reviewed by humans → rehydrate the real customer name.
            return rehydrate(draft.text, context), "llm"
        except NarrationFailed as failure:
            logger.warning(
                "draft message narration failed for task %d (%s); falling back to template",
                row["task_id"],
                failure.reason,
            )
    return _template_message(row["rule"], row["evidence"], row["customer_name"]), "template"


def _template_message(rule: str, evidence: dict[str, Any], customer_name: str) -> str:
    """Deterministic Bosnian win-back message (pure formatting of SQL values)."""
    if rule == "customer_decline":
        return (
            f"Poštovani ({customer_name}),\n\n"
            f"primijetili smo da su Vaše narudžbe u posljednjem periodu smanjene — "
            f"promet iznosi {evidence['value']} KM, dok je ranije uobičajeno bio "
            f"{evidence['baseline']} KM. Voljeli bismo provjeriti možemo li nešto "
            f"poboljšati u našoj saradnji i stojimo Vam na raspolaganju.\n\n"
            f"Srdačan pozdrav"
        )
    # sleeping_customer
    return (
        f"Poštovani ({customer_name}),\n\n"
        f"primijetili smo da niste naručivali od {evidence['last_order_date']}. "
        f"Voljeli bismo provjeriti trebate li pomoć oko nove narudžbe i možemo li "
        f"nešto poboljšati u našoj saradnji.\n\n"
        f"Srdačan pozdrav"
    )
