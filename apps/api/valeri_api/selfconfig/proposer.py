"""The rule-change proposer (M10): dismissal/feedback → structured, resolved draft.

Flow: dismiss the signal (+ its task) → mask → Tier-1 structures the change →
resolve pseudonym refs to real ids (server-side) → SQL blast radius →
deterministic autonomy decision → persist the learned rule:
  - auto_apply       → status='active'  + reversible app.decision (actor=valeri)
  - requires_confirm → status='pending_confirm' (no decision until the human confirms)
"""

import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.audit.task_log import log_task_event
from valeri_api.auth.models import AppUser
from valeri_api.llm.client import LLMClient
from valeri_api.llm.masking import MaskingContext, mask_text
from valeri_api.llm.prompts import RULE_PROPOSAL_SYSTEM_PROMPT
from valeri_api.llm.schemas import NarrationFailed
from valeri_api.llm.structured import narrate_structured
from valeri_api.rules.models import LearnedRule
from valeri_api.selfconfig.applier import auto_apply_rule
from valeri_api.selfconfig.autonomy import decide_autonomy
from valeri_api.selfconfig.effect import estimate_effect
from valeri_api.selfconfig.schemas import (
    DismissResponse,
    LearnedRuleRead,
    RuleChangeProposal,
)

logger = logging.getLogger("valeri.selfconfig.proposer")


class ProposalFailed(Exception):
    """The reason could not be structured into a rule change (LLM failure)."""


class SignalNotFound(LookupError):
    """The referenced signal does not exist."""


def propose_from_dismissal(
    session: Session,
    signal_id: int,
    reason_text: str,
    user: AppUser,
    client: LLMClient | None = None,
    source_message_id: int | None = None,
) -> DismissResponse:
    """The full dismissal flow. Returns the proposal + what happened (applied or pending)."""
    signal = (
        session.execute(
            text(
                "SELECT s.id, s.rule, s.customer_id, s.article_id, s.evidence, "
                "       c.name AS customer_name, c.segment "
                "FROM app.signal s LEFT JOIN core.customer c ON c.id = s.customer_id "
                "WHERE s.id = :id"
            ),
            {"id": signal_id},
        )
        .mappings()
        .one_or_none()
    )
    if signal is None:
        raise SignalNotFound(f"Signal {signal_id} ne postoji")

    # ── 1. dismiss the signal + its open task (D6) ────────────────────────────
    _dismiss_signal_and_task(session, signal_id, reason_text, user)

    # ── 2. mask the reason + signal context (principle 6) ────────────────────
    context = MaskingContext()
    resolved_entities = []
    if signal["customer_id"] is not None:
        # Register the signal's customer so the prompt references it by pseudonym
        # and scope resolution can map that pseudonym back to the real id.
        context.register_customer(signal["customer_id"], signal["customer_name"] or "")
        resolved_entities = [
            (signal["customer_name"], signal["customer_id"], signal["customer_name"])
        ]
    masked_reason = mask_text(reason_text, resolved_entities, context)

    masked_payload = {
        "razlog_korisnika": masked_reason,
        "signal": {
            "pravilo": signal["rule"],
            "kupac": context.pseudonyms and next(iter(context.pseudonyms)) or None,
            "segment": signal["segment"],
        },
    }

    # ── 3. Tier-1 structures the rule change ──────────────────────────────────
    try:
        proposal, _, _ = narrate_structured(
            session,
            masked_payload,
            RuleChangeProposal,
            system_prompt=RULE_PROPOSAL_SYSTEM_PROMPT,
            instruction=(
                "Pretvori razlog odbacivanja u najužu moguću strukturiranu promjenu pravila."
            ),
            client=client,
            text_field="description",
            register="preporuka",
        )
    except NarrationFailed as failure:
        raise ProposalFailed(
            f"Razlog nije moguće strukturirati u pravilo: {failure.reason}"
        ) from failure

    # ── 4. resolve pseudonym refs → real ids (server-side, never the model) ──
    resolved_scope = _resolve_scope(proposal, signal, context)

    # ── 5. SQL blast radius + deterministic autonomy ──────────────────────────
    effect = estimate_effect(session, resolved_scope)
    autonomy = decide_autonomy(session, resolved_scope, effect, proposal.interpretation_confidence)

    # ── 6. persist ────────────────────────────────────────────────────────────
    learned_rule = LearnedRule(
        source_signal_id=signal_id,
        source_message_id=source_message_id,
        domain="sales",
        rule_type=proposal.rule_type,
        scope=resolved_scope,
        description=proposal.description,
        effect_estimate=effect.model_dump(),
        status="pending_confirm",
        autonomy="confirmed",  # overwritten to auto_applied below when autonomy allows
        created_by=user.id,
    )
    session.add(learned_rule)
    session.flush()

    decision_id: int | None = None
    if autonomy == "auto_apply":
        decision = auto_apply_rule(session, learned_rule, user)
        decision_id = decision.id

    applied = autonomy == "auto_apply"
    return DismissResponse(
        signal_id=signal_id,
        proposal=proposal,
        effect_estimate=effect,
        requires_confirm=not applied,
        applied=applied,
        learned_rule=_rule_read(learned_rule),
        decision_id=decision_id,
        register="akcija" if applied else "preporuka",
    )


# ── helpers ───────────────────────────────────────────────────────────────────


def _dismiss_signal_and_task(
    session: Session, signal_id: int, reason_text: str, user: AppUser
) -> None:
    """Mark the signal dismissed and dismiss its open task (one gesture, D6)."""
    session.execute(
        text("UPDATE app.signal SET status = 'dismissed' WHERE id = :id"), {"id": signal_id}
    )
    task_id = session.execute(
        text(
            "UPDATE app.task SET status = 'dismissed' "
            "WHERE signal_id = :id AND status IN ('open', 'in_progress') RETURNING id"
        ),
        {"id": signal_id},
    ).scalar()
    if task_id is not None:
        log_task_event(
            session,
            task_id,
            "outcome",
            {"status": "dismissed", "reason": reason_text, "by_user": user.id},
        )


def _resolve_scope(proposal: RuleChangeProposal, signal, context: MaskingContext) -> dict:
    """Build the persisted scope: pseudonym refs → real ids; no pseudonyms stored."""
    scope = proposal.scope.model_dump(exclude_none=True)
    entity_ref = scope.pop("entity_ref", None)

    if scope.get("kind") in ("entity", "once"):
        # Resolve the pseudonym the model referenced; fall back to the dismissed
        # signal's own customer/article (the narrowest sensible target).
        entity_id = context.customer_id_for(entity_ref) if entity_ref else None
        if scope.get("entity_type") == "article":
            scope["entity_id"] = signal["article_id"]
        else:
            scope["entity_type"] = "customer"
            scope["entity_id"] = entity_id or signal["customer_id"]
        if scope["kind"] == "once":
            # 'once' scopes pin both customer and article of the dismissed signal.
            scope["customer_id"] = signal["customer_id"]
            scope["article_id"] = signal["article_id"]

    # A proposal that names no rule defaults to the dismissed signal's rule —
    # never wider than what the user dismissed unless they explicitly said so.
    scope.setdefault("rule", signal["rule"])
    return scope


def _rule_read(rule: LearnedRule) -> LearnedRuleRead:
    return LearnedRuleRead(
        id=rule.id,
        source_signal_id=rule.source_signal_id,
        source_message_id=rule.source_message_id,
        domain=rule.domain,
        rule_type=rule.rule_type,
        scope=rule.scope,
        description=rule.description,
        effect_estimate=rule.effect_estimate,
        status=rule.status,
        autonomy=rule.autonomy,
        created_by=rule.created_by,
        created_at=rule.created_at,
        expires_at=rule.expires_at,
    )


def propose_from_text(
    session: Session,
    reason_text: str,
    user: AppUser,
    client: LLMClient | None = None,
    source_message_id: int | None = None,
) -> DismissResponse:
    """Feedback without a signal (chat feedback_config intent).

    Entities mentioned in the text are resolved server-side; an entity-scoped
    proposal that names no resolvable customer fails rather than guessing.
    """
    from valeri_api.conversation.resolution import resolve_entities

    # ── 1. resolve + mask the free-text reason ────────────────────────────────
    context = MaskingContext()
    resolved_entities = resolve_entities(session, reason_text)
    masked_reason = mask_text(reason_text, resolved_entities, context)

    masked_payload = {
        "razlog_korisnika": masked_reason,
        "signal": None,  # no source signal — pure feedback
    }

    # ── 2. Tier-1 structures the rule change ──────────────────────────────────
    try:
        proposal, _, _ = narrate_structured(
            session,
            masked_payload,
            RuleChangeProposal,
            system_prompt=RULE_PROPOSAL_SYSTEM_PROMPT,
            instruction=(
                "Pretvori povratnu informaciju korisnika u najužu moguću strukturiranu "
                "promjenu pravila."
            ),
            client=client,
            text_field="description",
            register="preporuka",
        )
    except NarrationFailed as failure:
        raise ProposalFailed(
            f"Povratnu informaciju nije moguće strukturirati u pravilo: {failure.reason}"
        ) from failure

    # ── 3. resolve scope refs (no signal fallback here) ──────────────────────
    scope = proposal.scope.model_dump(exclude_none=True)
    entity_ref = scope.pop("entity_ref", None)
    if scope.get("kind") in ("entity", "once"):
        entity_id = context.customer_id_for(entity_ref) if entity_ref else None
        if entity_id is None:
            raise ProposalFailed(
                "Pravilo se odnosi na konkretnog kupca, ali kupac iz poruke nije prepoznat — "
                "navedite tačno ime kupca"
            )
        scope["entity_type"] = scope.get("entity_type") or "customer"
        scope["entity_id"] = entity_id

    # ── 4. SQL blast radius + deterministic autonomy ──────────────────────────
    effect = estimate_effect(session, scope)
    autonomy = decide_autonomy(session, scope, effect, proposal.interpretation_confidence)

    # ── 5. persist ────────────────────────────────────────────────────────────
    learned_rule = LearnedRule(
        source_signal_id=None,
        source_message_id=source_message_id,
        domain="sales",
        rule_type=proposal.rule_type,
        scope=scope,
        description=proposal.description,
        effect_estimate=effect.model_dump(),
        status="pending_confirm",
        autonomy="confirmed",
        created_by=user.id,
    )
    session.add(learned_rule)
    session.flush()

    decision_id: int | None = None
    if autonomy == "auto_apply":
        decision = auto_apply_rule(session, learned_rule, user)
        decision_id = decision.id

    applied = autonomy == "auto_apply"
    return DismissResponse(
        signal_id=0,  # no source signal
        proposal=proposal,
        effect_estimate=effect,
        requires_confirm=not applied,
        applied=applied,
        learned_rule=_rule_read(learned_rule),
        decision_id=decision_id,
        register="akcija" if applied else "preporuka",
    )
