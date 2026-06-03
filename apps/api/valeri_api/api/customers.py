"""Customers API (M8): list/search, 360 detail, at-risk table — per docs/api-spec.md.

All authenticated roles may call these; sales reps are row-scoped to their own
customers via visible_customer_ids() (RBAC). Numbers come from SQL only.
"""

import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.audit.serialization import jsonable
from valeri_api.auth.deps import CurrentUser, visible_customer_ids
from valeri_api.db import get_session
from valeri_api.metrics.dashboard import at_risk_rows, customer_360
from valeri_api.metrics.schemas import AtRiskRow, Customer360

router = APIRouter()


class CustomerRow(BaseModel):
    """One customer list row (metrics joined from SQL)."""

    id: int
    name: str
    segment: str | None
    status: str
    legal_entity_id: int
    legal_entity_name: str | None
    turnover_60d: str | None
    baseline_60d: str | None
    last_order_date: str | None
    risk_band: str | None  # from the strongest open decline signal, if any


class CustomerListResponse(BaseModel):
    items: list[CustomerRow]
    next_cursor: int | None = None


class CustomerDetail(BaseModel):
    """Customer 360: header + contacts + metrics + open signals/tasks."""

    customer: CustomerRow
    contacts: list[dict[str, Any]]
    metrics: Customer360 | None
    signals: list[dict[str, Any]]
    tasks: list[dict[str, Any]]


class AtRiskListResponse(BaseModel):
    items: list[AtRiskRow]


_CUSTOMER_SELECT = """
SELECT c.id,
       c.name,
       c.segment,
       c.status,
       c.legal_entity_id,
       le.name AS legal_entity_name,
       m.turnover_60d,
       m.turnover_6m_avg_60d AS baseline_60d,
       m.last_order_date,
       (SELECT CASE s.conf_band::text
                    WHEN 'visoka' THEN 'visok'
                    WHEN 'srednja' THEN 'srednji'
                    ELSE 'nizak'
               END
        FROM app.signal s
        WHERE s.customer_id = c.id
          AND s.rule = 'customer_decline'
          AND s.status IN ('new', 'tasked')
        ORDER BY s.confidence DESC
        LIMIT 1) AS risk_band
FROM core.customer c
LEFT JOIN core.legal_entity le ON le.id = c.legal_entity_id
LEFT JOIN core.customer_metrics m ON m.customer_id = c.id
"""


def _row_to_customer(row) -> CustomerRow:
    return CustomerRow(**jsonable(dict(row)))


def _forbidden() -> HTTPException:
    return HTTPException(
        status_code=403,
        detail={"code": "forbidden", "message": "Nemate pristup ovom kupcu"},
    )


@router.get("/customers", response_model=CustomerListResponse)
def list_customers(
    session: Annotated[Session, Depends(get_session)],
    user: CurrentUser,
    query: str | None = None,
    segment: str | None = None,
    risk: str | None = None,
    limit: int = 50,
    cursor: int | None = None,
) -> CustomerListResponse:
    """List/search customers; reps see only their own."""
    limit = max(1, min(limit, 200))
    scope = visible_customer_ids(user, session)

    rows = session.execute(
        text(_CUSTOMER_SELECT + """
            WHERE (CAST(:query AS text) IS NULL OR c.name ILIKE '%' || :query || '%')
              AND (CAST(:segment AS text) IS NULL OR c.segment = :segment)
              AND (CAST(:cursor AS bigint) IS NULL OR c.id > :cursor)
              AND (CAST(:scoped AS boolean) IS FALSE
                   OR c.id = ANY(CAST(:customer_ids AS bigint[])))
            ORDER BY c.id
            LIMIT :limit_plus_one
            """),
        {
            "query": query,
            "segment": segment,
            "cursor": cursor,
            "scoped": scope is not None,
            "customer_ids": sorted(scope) if scope is not None else [],
            "limit_plus_one": limit + 1,
        },
    ).mappings()

    items = [_row_to_customer(row) for row in rows]
    # The risk filter applies to the SQL-derived band (pass-through filtering).
    if risk is not None:
        items = [item for item in items if item.risk_band == risk]

    has_more = len(items) > limit
    items = items[:limit]
    return CustomerListResponse(
        items=items, next_cursor=items[-1].id if has_more and items else None
    )


@router.get("/customers/at-risk", response_model=AtRiskListResponse)
def list_at_risk(
    session: Annotated[Session, Depends(get_session)],
    user: CurrentUser,
    limit: int = 20,
) -> AtRiskListResponse:
    """The customers-at-risk table (decline signals), rep-scoped."""
    scope = visible_customer_ids(user, session)
    return AtRiskListResponse(
        items=at_risk_rows(session, limit=max(1, min(limit, 100)), customer_ids=scope)
    )


@router.get("/customers/{customer_id}", response_model=CustomerDetail)
def get_customer(
    customer_id: int,
    session: Annotated[Session, Depends(get_session)],
    user: CurrentUser,
) -> CustomerDetail:
    """Customer 360: header, contacts, metrics, open signals and tasks."""
    scope = visible_customer_ids(user, session)
    if scope is not None and customer_id not in scope:
        raise _forbidden()

    row = (
        session.execute(text(_CUSTOMER_SELECT + " WHERE c.id = :id"), {"id": customer_id})
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": f"Customer {customer_id} not found"},
        )

    contacts = session.execute(
        text("SELECT id, name, email, phone, address FROM core.contact WHERE customer_id = :id"),
        {"id": customer_id},
    ).mappings()
    signals = session.execute(
        text(
            "SELECT id, rule, evidence, confidence, conf_band, register, status, created_at "
            "FROM app.signal WHERE customer_id = :id ORDER BY id DESC LIMIT 20"
        ),
        {"id": customer_id},
    ).mappings()
    tasks = session.execute(
        text(
            "SELECT t.id, t.title, t.status, t.due_date, t.register "
            "FROM app.task t JOIN app.signal s ON s.id = t.signal_id "
            "WHERE s.customer_id = :id ORDER BY t.id DESC LIMIT 20"
        ),
        {"id": customer_id},
    ).mappings()

    return CustomerDetail(
        customer=_row_to_customer(row),
        contacts=[jsonable(dict(contact)) for contact in contacts],
        metrics=customer_360(session, customer_id, as_of=datetime.date.today()),
        signals=[jsonable(dict(signal)) for signal in signals],
        tasks=[jsonable(dict(task)) for task in tasks],
    )
