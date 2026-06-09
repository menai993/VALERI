"""Reps & activity API (C-CRM2) — per docs/api-spec.md.

RBAC: view activity = owner/admin/finance/sales_rep (rep → own row); log activity =
owner/admin/sales_rep (rep → own; owner/admin may log for any rep). Finance read-only.
Activities are VALERI-native data; the ERP is never written.
"""

import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.auth.deps import CurrentUser, require_roles
from valeri_api.auth.models import AppUser
from valeri_api.crm import activity as activity_service
from valeri_api.crm.probability import ACTIVITY_KINDS
from valeri_api.crm.schemas import ActivityCreate, ActivityRead, RepActivityBlock
from valeri_api.db import get_session

router = APIRouter()

# log activity: reps (own) + owner/admin (any); finance excluded.
Logger = Annotated[AppUser, Depends(require_roles("owner", "admin", "sales_rep"))]


@router.get("/reps")
def list_reps(
    session: Annotated[Session, Depends(get_session)],
    user: CurrentUser,
) -> dict:
    """The sales-rep directory (id, name) — powers assignee selects (P1).

    Plain internal directory data (already exposed as assignee_name on tasks).
    """
    rows = session.execute(text("SELECT id, name FROM core.sales_rep ORDER BY name")).all()
    return {"items": [{"id": row.id, "name": row.name} for row in rows]}


@router.get("/reps/activity", response_model=RepActivityBlock)
def get_rep_activity(
    session: Annotated[Session, Depends(get_session)],
    user: CurrentUser,
    date: str | None = None,
) -> RepActivityBlock:
    """Per-rep activity rollup for the month of `date` (default today)."""
    if date is not None:
        try:
            as_of = datetime.date.fromisoformat(date)
        except ValueError as error:
            raise HTTPException(
                status_code=422,
                detail={"code": "invalid_date", "message": f"Neispravan datum: {date}"},
            ) from error
    else:
        as_of = datetime.date.today()

    # A rep sees only their own row; everyone else (owner/admin/finance) sees all.
    rep_scope = user.sales_rep_id if user.role == "sales_rep" else None
    return activity_service.rep_activity_rollup(session, as_of, sales_rep_id=rep_scope)


@router.post("/activity", status_code=201, response_model=ActivityRead)
def log_activity(
    body: ActivityCreate,
    session: Annotated[Session, Depends(get_session)],
    user: Logger,
) -> ActivityRead:
    """Log one activity. A rep logs their own (sales_rep_id forced); owner/admin any."""
    if body.kind not in ACTIVITY_KINDS:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_kind", "message": f"Nepoznata vrsta aktivnosti: {body.kind}"},
        )

    # A rep's activity is always theirs; owner/admin may name any rep.
    if user.role == "sales_rep":
        if user.sales_rep_id is None:
            raise HTTPException(
                status_code=403,
                detail={"code": "forbidden", "message": "Korisnik nije povezan s komercijalistom"},
            )
        sales_rep_id = user.sales_rep_id
    else:
        if body.sales_rep_id is None:
            raise HTTPException(
                status_code=422,
                detail={"code": "missing_rep", "message": "sales_rep_id je obavezan"},
            )
        sales_rep_id = body.sales_rep_id

    result = activity_service.log_activity(
        session,
        sales_rep_id=sales_rep_id,
        kind=body.kind,
        customer_id=body.customer_id,
        done=body.done,
        at=body.at,
    )
    session.commit()
    return result
