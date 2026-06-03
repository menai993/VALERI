"""Signals API (M8): list/detail + feedback — per docs/api-spec.md.

All authenticated roles; reps see only their own customers' signals. The
self-config dismissal endpoint (POST /signals/{id}/dismiss → learned-rule draft)
lands in M10; the M8 UI RuleCard is preview-only (D3).
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.audit.serialization import jsonable
from valeri_api.audit.task_log import log_task_event
from valeri_api.auth.deps import CurrentUser, visible_customer_ids
from valeri_api.db import get_session
from valeri_api.signals.models import TaskFeedback

router = APIRouter()


class SignalRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rule: str
    customer_id: int | None
    customer_name: str | None
    article_id: int | None
    evidence: dict[str, Any]
    confidence: str
    conf_band: str
    register: str
    status: str
    created_at: str
    task_id: int | None


class SignalListResponse(BaseModel):
    items: list[SignalRow]
    next_cursor: int | None = None


class SignalFeedbackCreate(BaseModel):
    useful: bool
    reason: str | None = None


class SignalFeedbackRead(BaseModel):
    signal_id: int
    task_id: int
    useful: bool
    reason: str | None


_SIGNAL_SELECT = """
SELECT s.id, s.rule, s.customer_id, c.name AS customer_name, s.article_id,
       s.evidence, s.confidence, s.conf_band, s.register, s.status, s.created_at,
       t.id AS task_id
FROM app.signal s
LEFT JOIN core.customer c ON c.id = s.customer_id
LEFT JOIN app.task t ON t.signal_id = s.id
"""


def _row_to_signal(row) -> SignalRow:
    return SignalRow(**jsonable(dict(row)))


def _not_found(signal_id: int) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"code": "not_found", "message": f"Signal {signal_id} not found"},
    )


def _scope_clause(scope: set[int] | None) -> dict[str, Any]:
    return {
        "scoped": scope is not None,
        "customer_ids": sorted(scope) if scope is not None else [],
    }


@router.get("/signals", response_model=SignalListResponse)
def list_signals(
    session: Annotated[Session, Depends(get_session)],
    user: CurrentUser,
    rule: str | None = None,
    conf: str | None = None,
    status: str | None = None,
    limit: int = 50,
    cursor: int | None = None,
) -> SignalListResponse:
    """List signals, filterable by rule/confidence-band/status; rep-scoped."""
    limit = max(1, min(limit, 200))
    scope = visible_customer_ids(user, session)

    rows = session.execute(
        text(_SIGNAL_SELECT + """
            WHERE (CAST(:rule AS text) IS NULL OR s.rule = :rule)
              AND (CAST(:conf AS text) IS NULL OR s.conf_band::text = :conf)
              AND (CAST(:status AS text) IS NULL OR s.status::text = :status)
              AND (CAST(:cursor AS bigint) IS NULL OR s.id > :cursor)
              AND (CAST(:scoped AS boolean) IS FALSE
                   OR s.customer_id = ANY(CAST(:customer_ids AS bigint[])))
            ORDER BY s.id
            LIMIT :limit_plus_one
            """),
        {
            "rule": rule,
            "conf": conf,
            "status": status,
            "cursor": cursor,
            "limit_plus_one": limit + 1,
            **_scope_clause(scope),
        },
    ).mappings()

    items = [_row_to_signal(row) for row in rows]
    has_more = len(items) > limit
    items = items[:limit]
    return SignalListResponse(items=items, next_cursor=items[-1].id if has_more and items else None)


@router.get("/signals/{signal_id}", response_model=SignalRow)
def get_signal(
    signal_id: int,
    session: Annotated[Session, Depends(get_session)],
    user: CurrentUser,
) -> SignalRow:
    """Signal detail with full evidence."""
    scope = visible_customer_ids(user, session)
    row = (
        session.execute(text(_SIGNAL_SELECT + " WHERE s.id = :id"), {"id": signal_id})
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise _not_found(signal_id)
    if scope is not None and row["customer_id"] not in scope:
        raise HTTPException(
            status_code=403,
            detail={"code": "forbidden", "message": "Nemate pristup ovom signalu"},
        )
    return _row_to_signal(row)


@router.post("/signals/{signal_id}/feedback", status_code=201, response_model=SignalFeedbackRead)
def add_signal_feedback(
    signal_id: int,
    body: SignalFeedbackCreate,
    session: Annotated[Session, Depends(get_session)],
    user: CurrentUser,
) -> SignalFeedbackRead:
    """Feedback on a signal — recorded on its task (the M10 learning loop's raw material)."""
    scope = visible_customer_ids(user, session)
    row = (
        session.execute(text(_SIGNAL_SELECT + " WHERE s.id = :id"), {"id": signal_id})
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise _not_found(signal_id)
    if scope is not None and row["customer_id"] not in scope:
        raise HTTPException(
            status_code=403,
            detail={"code": "forbidden", "message": "Nemate pristup ovom signalu"},
        )
    if row["task_id"] is None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "conflict",
                "message": f"Signal {signal_id} has no task to attach feedback to",
            },
        )

    feedback = TaskFeedback(
        task_id=row["task_id"], useful=body.useful, reason=body.reason, by_user=user.id
    )
    session.add(feedback)
    session.flush()
    log_task_event(
        session,
        row["task_id"],
        "feedback",
        {"useful": body.useful, "reason": body.reason, "signal_id": signal_id},
    )
    session.commit()

    return SignalFeedbackRead(
        signal_id=signal_id, task_id=row["task_id"], useful=body.useful, reason=body.reason
    )
