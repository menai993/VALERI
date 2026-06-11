"""The investigation lifecycle (M13): create → run (async) → needs_input → resume → done.

The runner owns the status transitions and the report write; the graph (and its
checkpointer) own the execution state, so a process restart resumes instead of
restarting. Every failure is recorded — an investigation never silently dies.
"""

import datetime
import logging
import time
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.auth.models import AppUser
from valeri_api.conversation.resolution import resolve_entities
from valeri_api.db import get_engine
from valeri_api.investigation.checkpoint import open_checkpointer
from valeri_api.investigation.graph import build_graph
from valeri_api.investigation.models import Investigation
from valeri_api.investigation.schemas import InvestigationState
from valeri_api.investigation.steps import record_step
from valeri_api.llm.client import LLMClient
from valeri_api.llm.masking import MaskingContext, mask_text

logger = logging.getLogger("valeri.investigation.runner")


class InvestigationNotFound(LookupError):
    """The referenced investigation does not exist."""


class InvalidInvestigationState(Exception):
    """The investigation is not in a state that allows this operation."""


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


# ── create ────────────────────────────────────────────────────────────────────


class FeatureCapReached(Exception):
    """The investigation daily cap is hit — refuse before queueing a run (P3)."""


def create_investigation(
    session: Session,
    question: str,
    user: AppUser,
    signal_id: int | None = None,
    trigger: str = "user",
) -> Investigation:
    """Queue a new investigation (the worker picks it up; nothing runs inline).

    P3: refuses with FeatureCapReached once the investigation daily cap is hit —
    the most expensive feature can't blow the budget in a single day.
    """
    from valeri_api.llm.spend_guard import feature_cap_reached

    if feature_cap_reached(session, "investigation"):
        raise FeatureCapReached("Dnevni limit istraga je dostignut — pokušajte ponovo sutra.")

    investigation = Investigation(
        trigger=trigger,
        question=question,
        status="queued",
        model_tier="tier2",
        created_by=user.id,
        signal_id=signal_id,
        thread_id=uuid.uuid4().hex,
    )
    session.add(investigation)
    session.flush()
    return investigation


# ── run ───────────────────────────────────────────────────────────────────────


def _initial_state(session: Session, investigation: Investigation) -> InvestigationState:
    """The masked starting state (entity resolution + masking happen ONCE, here)."""
    context = MaskingContext()
    resolved = resolve_entities(session, investigation.question)
    question_masked = mask_text(investigation.question, resolved, context)
    return {
        "investigation_id": investigation.id,
        "user_id": investigation.created_by,
        "question_masked": question_masked,
        "pseudonyms": dict(context.pseudonyms),
        "pseudonym_ids": dict(context.customer_ids),
        "plan": [],
        "act_count": 0,
        "tokens_used": 0,
        "started_ts": time.time(),
        "tool_results": [],
        "proposed_actions": [],
        "critic_verdict": None,
        "budget_exhausted": None,
        "hitl_decision": None,
        "failure": None,
    }


def run_investigation(investigation_id: int, client: LLMClient | None = None) -> Investigation:
    """Run one queued investigation until done / needs_input / failed."""
    engine = get_engine()

    def session_factory() -> Session:
        return Session(engine)

    # ── queued → running + build the initial (masked) state ──────────────────
    with Session(engine) as session:
        investigation = session.get(Investigation, investigation_id)
        if investigation is None:
            raise InvestigationNotFound(f"Istraga {investigation_id} ne postoji")
        if investigation.status != "queued":
            raise InvalidInvestigationState(
                f"Istraga {investigation_id} je u statusu {investigation.status!r} — "
                "samo istrage u redu (queued) se mogu pokrenuti"
            )
        investigation.status = "running"
        investigation.started_at = _now()
        initial_state = _initial_state(session, investigation)
        thread_id = investigation.thread_id
        session.commit()

    return _execute(engine, investigation_id, thread_id, initial_state, client, session_factory)


def resume_investigation(
    investigation_id: int, decision: str, client: LLMClient | None = None
) -> Investigation:
    """Satisfy the HITL interrupt (approve/reject the proposed actions) and continue."""
    engine = get_engine()

    def session_factory() -> Session:
        return Session(engine)

    with Session(engine) as session:
        investigation = session.get(Investigation, investigation_id)
        if investigation is None:
            raise InvestigationNotFound(f"Istraga {investigation_id} ne postoji")
        if investigation.status != "needs_input":
            raise InvalidInvestigationState(
                f"Istraga {investigation_id} je u statusu {investigation.status!r} — "
                "samo istrage koje čekaju odluku se mogu nastaviti"
            )
        investigation.status = "running"
        thread_id = investigation.thread_id
        record_step(
            session,
            investigation_id,
            node="hitl",
            output_payload={"decision": decision},
        )
        session.commit()

    return _execute(
        engine,
        investigation_id,
        thread_id,
        None,  # resume from the checkpoint, not a fresh state
        client,
        session_factory,
        hitl_decision=decision,
    )


def _execute(
    engine,
    investigation_id: int,
    thread_id: str,
    initial_state: InvestigationState | None,
    client: LLMClient | None,
    session_factory,
    hitl_decision: str | None = None,
) -> Investigation:
    """Invoke the graph and translate its outcome into investigation status/report."""
    config = {"configurable": {"thread_id": thread_id}}

    try:
        with open_checkpointer() as checkpointer:
            graph = build_graph(session_factory, client, checkpointer)
            if hitl_decision is not None:
                # The human's decision enters the checkpointed state before resuming.
                graph.update_state(config, {"hitl_decision": hitl_decision})
            final_state = graph.invoke(initial_state, config)
            interrupted = bool(graph.get_state(config).next)
    except Exception as error:  # noqa: BLE001 — a failed run must NEVER die silently
        logger.exception("investigation %d failed", investigation_id)
        with Session(engine) as session:
            investigation = session.get(Investigation, investigation_id)
            investigation.status = "failed"
            investigation.finished_at = _now()
            record_step(
                session,
                investigation_id,
                node="error",
                output_payload={"error": str(error)},
            )
            session.commit()
            session.refresh(investigation)
            return investigation

    # ── outcome → status/report ───────────────────────────────────────────────
    with Session(engine) as session:
        investigation = session.get(Investigation, investigation_id)
        if interrupted:
            # Stopped before execute_action: the human must approve/reject.
            investigation.status = "needs_input"
        else:
            investigation.status = "done"
            investigation.finished_at = _now()
            investigation.report = final_state.get("report")
        session.commit()
        session.refresh(investigation)
        logger.info(
            "investigation %d → %s (steps=%s, tokens=%s)",
            investigation_id,
            investigation.status,
            final_state.get("act_count"),
            final_state.get("tokens_used"),
        )
        return investigation


# ── the worker entry ──────────────────────────────────────────────────────────


def poll_queued(client: LLMClient | None = None) -> int | None:
    """Run the oldest queued investigation (one at a time). Returns its id or None."""
    engine = get_engine()
    with Session(engine) as session:
        investigation_id = session.execute(
            text("SELECT id FROM app.investigation WHERE status = 'queued' ORDER BY id LIMIT 1")
        ).scalar()

    if investigation_id is None:
        return None

    run_investigation(investigation_id, client=client)
    return investigation_id


# ── read helpers (used by the API) ────────────────────────────────────────────


def pending_actions(session: Session, investigation_id: int) -> list[dict]:
    """The proposed actions awaiting the HITL decision (from the append-only trace)."""
    rows = session.execute(
        text(
            "SELECT output->'proposed_action' AS proposal FROM app.investigation_step "
            "WHERE investigation_id = :id AND output ? 'proposed_action' ORDER BY step_no"
        ),
        {"id": investigation_id},
    ).all()
    return [row.proposal for row in rows]
