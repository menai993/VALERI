"""Opportunities API (C-CRM1) — CRUD + pipeline, per docs/api-spec.md.

RBAC (spec D3): view = owner/admin/finance/sales_rep (rep → own customers);
create/update = owner/admin/sales_rep (rep → own customers only); finance read-only.
The ERP is never written — opportunities are VALERI-native data.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from valeri_api.auth.deps import CurrentUser, require_roles, visible_customer_ids
from valeri_api.auth.models import AppUser
from valeri_api.crm import service
from valeri_api.crm.probability import ALL_STAGES
from valeri_api.crm.schemas import (
    OpportunityCreate,
    OpportunityListResponse,
    OpportunityRead,
    OpportunityUpdate,
    PipelineResponse,
)
from valeri_api.crm.service import OpportunityNotFound
from valeri_api.db import get_session

router = APIRouter()

# create/update: reps may write (scoped); finance may not.
Writer = Annotated[AppUser, Depends(require_roles("owner", "admin", "sales_rep"))]


def _not_found(opportunity_id: int) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"code": "not_found", "message": f"Prilika {opportunity_id} ne postoji"},
    )


def _assert_customer_writable(user: AppUser, session: Session, customer_id: int) -> set[int] | None:
    """A rep may only write opportunities for their own customers (fail closed)."""
    scope = visible_customer_ids(user, session)
    if scope is not None and customer_id not in scope:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "forbidden",
                "message": "Komercijalista može upravljati prilikama samo svojih kupaca",
            },
        )
    return scope


# ── list ──────────────────────────────────────────────────────────────────────


@router.get("/opportunities", response_model=OpportunityListResponse)
def list_opportunities(
    session: Annotated[Session, Depends(get_session)],
    user: CurrentUser,
    stage: str | None = None,
    customer_id: int | None = None,
) -> OpportunityListResponse:
    """All opportunities the user may see (a rep → their own customers')."""
    if stage is not None and stage not in ALL_STAGES:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_stage", "message": f"Nepoznata faza: {stage}"},
        )
    scope = visible_customer_ids(user, session)
    items = service.list_opportunities(session, scope, stage=stage, customer_id=customer_id)
    return OpportunityListResponse(items=items)


# ── pipeline ──────────────────────────────────────────────────────────────────


@router.get("/opportunities/pipeline", response_model=PipelineResponse)
def get_pipeline(
    session: Annotated[Session, Depends(get_session)],
    user: CurrentUser,
) -> PipelineResponse:
    """Kanban columns + probability-weighted value + conversion rate (all SQL)."""
    scope = visible_customer_ids(user, session)
    return service.pipeline(session, scope)


# ── create ────────────────────────────────────────────────────────────────────


@router.post("/opportunities", status_code=201, response_model=OpportunityRead)
def create_opportunity(
    body: OpportunityCreate,
    session: Annotated[Session, Depends(get_session)],
    user: Writer,
) -> OpportunityRead:
    """Create an opportunity (+ its initial stage_history). Reps → own customers only."""
    scope = _assert_customer_writable(user, session, body.customer_id)

    # A rep's opportunity is owned by that rep (ignore any owner_rep_id they sent).
    owner_rep_id = body.owner_rep_id
    if scope is not None:
        owner_rep_id = user.sales_rep_id

    opportunity = service.create_opportunity(
        session,
        customer_id=body.customer_id,
        title=body.title,
        stage=body.stage,
        value=body.value,
        probability=body.probability,
        source=body.source,
        expected_close=body.expected_close,
        owner_rep_id=owner_rep_id,
    )
    session.commit()
    return opportunity


# ── update ────────────────────────────────────────────────────────────────────


@router.patch("/opportunities/{opportunity_id}", response_model=OpportunityRead)
def update_opportunity(
    opportunity_id: int,
    body: OpportunityUpdate,
    session: Annotated[Session, Depends(get_session)],
    user: Writer,
) -> OpportunityRead:
    """Patch an opportunity; a stage change appends history. Reps → own customers only."""
    try:
        existing = service.get_opportunity(session, opportunity_id)
    except OpportunityNotFound as error:
        raise _not_found(opportunity_id) from error

    _assert_customer_writable(user, session, existing.customer_id)

    changes = body.model_dump(exclude_unset=True)
    try:
        updated = service.update_opportunity(session, opportunity_id, changes)
    except OpportunityNotFound as error:
        raise _not_found(opportunity_id) from error
    session.commit()
    return updated
