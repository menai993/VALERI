"""Create / approve / reject / undo capability proposals (CSA Phase 3a).

A proposal is INERT until approved; approval runs the full SQL safety validator
(incl. EXPLAIN) and, only on success, flips it to 'active' so it joins the
registry overlay. Every consequential change writes an append-only, reversible
app.decision — the same discipline as the M10 self-config applier.
"""

import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.audit.decision import log_decision
from valeri_api.auth.models import AppUser
from valeri_api.capabilities.models import CapabilityProposal
from valeri_api.capabilities.schemas import (
    ProposalCreate,
    ProposalDecisionResponse,
    ProposalRead,
)
from valeri_api.selfconfig.applier import _decision_read  # shared DecisionRead mapper
from valeri_api.semantic.proposal_safety import UnsafeMetricSQL, validate_metric_sql

logger = logging.getLogger("valeri.capabilities.applier")


class ProposalNotFound(LookupError):
    """The referenced proposal does not exist."""


class InvalidProposalState(Exception):
    """The proposal is not in a state that allows this operation."""


def _get(session: Session, proposal_id: int) -> CapabilityProposal:
    proposal = session.get(CapabilityProposal, proposal_id)
    if proposal is None:
        raise ProposalNotFound(f"Prijedlog metrike {proposal_id} ne postoji")
    return proposal


def _declared(proposal: CapabilityProposal | ProposalCreate) -> set[str]:
    return {(param["name"] if isinstance(param, dict) else param.name) for param in proposal.params}


def create_proposal(session: Session, data: ProposalCreate, user: AppUser) -> CapabilityProposal:
    """Store a drafted proposal as INERT (status='proposed').

    Runs the STATIC safety checks now to reject obviously-unsafe drafts early;
    the full EXPLAIN check runs at approval. No decision is written — a draft
    changes no config (it is inert); approval is the consequential, logged step.
    """
    validate_metric_sql(data.sql, _declared(data))  # static only (no session) → raises if unsafe
    if session.execute(
        text("SELECT 1 FROM app.capability_proposal WHERE name = :n AND status = 'active'"),
        {"n": data.name},
    ).scalar():
        raise InvalidProposalState(f"Metrika {data.name!r} je već aktivna")

    proposal = CapabilityProposal(
        name=data.name,
        description=data.description,
        entity=data.entity,
        grain=data.grain,
        params=[param.model_dump() for param in data.params],
        sql=data.sql,
        status="proposed",
        source_message_id=data.source_message_id,
        created_by=user.id,
    )
    session.add(proposal)
    session.flush()
    return proposal


def approve_proposal(session: Session, proposal_id: int, user: AppUser) -> ProposalDecisionResponse:
    """Activate a proposal after the FULL safety validation (incl. EXPLAIN)."""
    proposal = _get(session, proposal_id)
    if proposal.status != "proposed":
        raise InvalidProposalState(
            f"Prijedlog {proposal_id} je u statusu {proposal.status!r} — "
            "samo predloženi prijedlozi se mogu odobriti"
        )
    # The wall: re-validate with EXPLAIN against the live DB before it ever runs.
    validate_metric_sql(proposal.sql, _declared(proposal), session=session)

    proposal.status = "active"
    proposal.activated_at = func_now(session)
    decision = log_decision(
        session,
        kind="approval",
        actor="user",
        summary=f"Aktivirana metrika: {proposal.name} — {proposal.description}",
        payload={
            "capability_proposal_id": proposal.id,
            "name": proposal.name,
            "sql": proposal.sql,
            "initiated_by_user_id": user.id,
        },
        reversible=True,
    )
    proposal.decision_id = decision.id
    session.flush()
    return ProposalDecisionResponse(
        proposal=ProposalRead.model_validate(proposal), decision=_decision_read(decision)
    )


def reject_proposal(session: Session, proposal_id: int, user: AppUser) -> ProposalDecisionResponse:
    """Reject a proposed metric (final)."""
    proposal = _get(session, proposal_id)
    if proposal.status != "proposed":
        raise InvalidProposalState(f"Prijedlog {proposal_id} je u statusu {proposal.status!r}")
    proposal.status = "rejected"
    decision = log_decision(
        session,
        kind="rejection",
        actor="user",
        summary=f"Odbijen prijedlog metrike: {proposal.name}",
        payload={"capability_proposal_id": proposal.id, "initiated_by_user_id": user.id},
        reversible=False,
    )
    proposal.decision_id = decision.id
    session.flush()
    return ProposalDecisionResponse(
        proposal=ProposalRead.model_validate(proposal), decision=_decision_read(decision)
    )


def undo_proposal(session: Session, proposal_id: int, user: AppUser) -> ProposalDecisionResponse:
    """Deactivate an ACTIVE metric: 'reverted' + a NEW undo decision (append-only)."""
    proposal = _get(session, proposal_id)
    if proposal.status != "active":
        raise InvalidProposalState(
            f"Prijedlog {proposal_id} je u statusu {proposal.status!r} — "
            "samo aktivne metrike se mogu deaktivirati"
        )
    original_decision_id = proposal.decision_id
    proposal.status = "reverted"
    decision = log_decision(
        session,
        kind="undo",
        actor="user",
        summary=f"Deaktivirana metrika: {proposal.name}",
        payload={
            "capability_proposal_id": proposal.id,
            "reverted_decision_id": original_decision_id,
            "initiated_by_user_id": user.id,
        },
        reversible=False,
        reverted_decision_id=original_decision_id,
    )
    proposal.decision_id = decision.id
    session.flush()
    return ProposalDecisionResponse(
        proposal=ProposalRead.model_validate(proposal), decision=_decision_read(decision)
    )


def func_now(session: Session):
    """DB clock (consistent with server_default=now())."""
    return session.execute(text("SELECT now()")).scalar()


__all__ = [
    "InvalidProposalState",
    "ProposalNotFound",
    "UnsafeMetricSQL",
    "approve_proposal",
    "create_proposal",
    "reject_proposal",
    "undo_proposal",
]
