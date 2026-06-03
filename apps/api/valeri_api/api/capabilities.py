"""Capability proposals API (CSA Phase 3a) — per docs/specs/csa-self-configuring-agent.md.

RBAC: create/approve/reject/undo + list = owner/admin (capabilities are
governance/finance). Approval runs the SQL safety validator (incl. EXPLAIN);
every consequential change writes a reversible app.decision via the applier.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from valeri_api.auth.deps import require_roles
from valeri_api.auth.models import AppUser
from valeri_api.capabilities.applier import (
    InvalidProposalState,
    ProposalNotFound,
    approve_proposal,
    create_proposal,
    reject_proposal,
    undo_proposal,
)
from valeri_api.capabilities.models import CapabilityProposal
from valeri_api.capabilities.schemas import (
    ProposalCreate,
    ProposalDecisionResponse,
    ProposalListResponse,
    ProposalRead,
)
from valeri_api.db import get_session
from valeri_api.semantic.proposal_safety import UnsafeMetricSQL

router = APIRouter()

Manager = Annotated[AppUser, Depends(require_roles("owner", "admin"))]


def _unsafe(error: UnsafeMetricSQL) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={"code": "unsafe_sql", "message": str(error), "details": {"reasons": error.reasons}},
    )


def _not_found(message: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": "not_found", "message": message})


def _conflict(message: str) -> HTTPException:
    return HTTPException(status_code=409, detail={"code": "conflict", "message": message})


@router.get("/capabilities/proposals", response_model=ProposalListResponse)
def list_proposals(
    session: Annotated[Session, Depends(get_session)],
    _user: Manager,
    status: str | None = None,
) -> ProposalListResponse:
    """All capability proposals, newest first (optionally filtered by status)."""
    stmt = select(CapabilityProposal).order_by(CapabilityProposal.id.desc())
    if status is not None:
        stmt = stmt.where(CapabilityProposal.status == status)
    rows = session.execute(stmt).scalars()
    return ProposalListResponse(items=[ProposalRead.model_validate(r) for r in rows])


@router.post("/capabilities/proposals", status_code=201, response_model=ProposalRead)
def post_proposal(
    body: ProposalCreate,
    session: Annotated[Session, Depends(get_session)],
    user: Manager,
) -> ProposalRead:
    """Draft a metric proposal (INERT — static-safety-checked, not yet active)."""
    try:
        proposal = create_proposal(session, body, user)
    except UnsafeMetricSQL as error:
        raise _unsafe(error) from error
    except InvalidProposalState as error:
        raise _conflict(str(error)) from error
    session.commit()
    return ProposalRead.model_validate(proposal)


@router.post("/capabilities/proposals/{proposal_id}/approve", response_model=ProposalDecisionResponse)
def approve(
    proposal_id: int,
    session: Annotated[Session, Depends(get_session)],
    user: Manager,
) -> ProposalDecisionResponse:
    """Activate a proposal after full SQL safety validation (incl. EXPLAIN)."""
    try:
        response = approve_proposal(session, proposal_id, user)
    except ProposalNotFound as error:
        raise _not_found(str(error)) from error
    except InvalidProposalState as error:
        raise _conflict(str(error)) from error
    except UnsafeMetricSQL as error:
        raise _unsafe(error) from error
    session.commit()
    return response


@router.post("/capabilities/proposals/{proposal_id}/reject", response_model=ProposalDecisionResponse)
def reject(
    proposal_id: int,
    session: Annotated[Session, Depends(get_session)],
    user: Manager,
) -> ProposalDecisionResponse:
    """Reject a proposed metric (final)."""
    try:
        response = reject_proposal(session, proposal_id, user)
    except ProposalNotFound as error:
        raise _not_found(str(error)) from error
    except InvalidProposalState as error:
        raise _conflict(str(error)) from error
    session.commit()
    return response


@router.post("/capabilities/proposals/{proposal_id}/undo", response_model=ProposalDecisionResponse)
def undo(
    proposal_id: int,
    session: Annotated[Session, Depends(get_session)],
    user: Manager,
) -> ProposalDecisionResponse:
    """Deactivate an active metric (reversible decision; removed from the overlay)."""
    try:
        response = undo_proposal(session, proposal_id, user)
    except ProposalNotFound as error:
        raise _not_found(str(error)) from error
    except InvalidProposalState as error:
        raise _conflict(str(error)) from error
    session.commit()
    return response
