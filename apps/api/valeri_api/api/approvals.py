"""Approvals API (M7): list pending approvals and decide them — per docs/api-spec.md.

Every item is register 'akcija' + an explicit status, so the owner always knows
whether something has happened. RBAC + decided_by from auth land in M8.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from valeri_api.approvals.models import APPROVAL_STATUSES, Approval
from valeri_api.approvals.schemas import ApprovalDecision, ApprovalListResponse, ApprovalRead
from valeri_api.approvals.workflow import InvalidTransition, decide
from valeri_api.db import get_session

router = APIRouter()


@router.get("/approvals", response_model=ApprovalListResponse)
def list_approvals(
    session: Annotated[Session, Depends(get_session)],
    status: str | None = None,
) -> ApprovalListResponse:
    """List approvals, filterable by status (e.g. ?status=pending_approval)."""
    if status is not None and status not in APPROVAL_STATUSES:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_status", "message": f"Unknown approval status {status!r}"},
        )

    query = select(Approval).order_by(Approval.id)
    if status is not None:
        query = query.where(Approval.status == status)

    approvals = session.execute(query).scalars().all()
    return ApprovalListResponse(items=[ApprovalRead.model_validate(a) for a in approvals])


@router.post("/approvals/{approval_id}/decide", response_model=ApprovalRead)
def decide_approval(
    approval_id: int,
    body: ApprovalDecision,
    session: Annotated[Session, Depends(get_session)],
) -> ApprovalRead:
    """Decide a pending approval (approved/rejected/deferred); records who/when."""
    try:
        approval = decide(session, approval_id, body.decision, note=body.note)
    except LookupError as error:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": str(error)}
        ) from error
    except InvalidTransition as error:
        raise HTTPException(
            status_code=409, detail={"code": "conflict", "message": str(error)}
        ) from error

    session.commit()
    session.refresh(approval)
    return ApprovalRead.model_validate(approval)
