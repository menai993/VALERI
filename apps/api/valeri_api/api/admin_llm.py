"""Admin LLM cost API (P3): the 'Troškovi AI' dashboard's data + the editors.

Read = owner/admin; write = admin. Every budget/pricing PATCH writes a reversible
threshold_change decision (the M10 decision-audit contract). All figures are SQL
over audit.ai_log — no LLM in this path.
"""

import datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.audit.decision import log_decision
from valeri_api.auth.deps import require_roles
from valeri_api.auth.models import AppUser
from valeri_api.db import get_session
from valeri_api.llm import cost

router = APIRouter()

_ReadUser = Annotated[AppUser, Depends(require_roles("owner", "admin"))]
_AdminUser = Annotated[AppUser, Depends(require_roles("admin"))]


# ── usage ─────────────────────────────────────────────────────────────────────


class UsageGroup(BaseModel):
    key: str | None
    cost_usd: Decimal
    calls: int
    input_tokens: int
    output_tokens: int


class UsageResponse(BaseModel):
    total: dict[str, Any]
    groups: list[UsageGroup]
    trend: list[dict[str, Any]]
    budget: dict[str, Any]
    cost_per_useful_task: dict[str, Any]


def _default_range() -> tuple[datetime.date, datetime.date]:
    today = datetime.date.today()
    return today.replace(day=1), today


@router.get("/admin/llm/usage", response_model=UsageResponse)
def llm_usage(
    session: Annotated[Session, Depends(get_session)],
    _user: _ReadUser,
    date_from: Annotated[datetime.date | None, Query(alias="from")] = None,
    date_to: Annotated[datetime.date | None, Query(alias="to")] = None,
    group_by: Annotated[str, Query()] = "feature",
) -> UsageResponse:
    """Spend + token aggregates, grouped, with the budget + cost-per-useful-task."""
    start, end = _default_range()
    date_from = date_from or start
    date_to = date_to or end
    agg = cost.usage_aggregates(session, date_from, date_to, group_by=group_by)
    return UsageResponse(
        total=agg["total"],
        groups=[UsageGroup(**g) for g in agg["groups"]],
        trend=agg["trend"],
        budget=cost.budget_status(session),
        cost_per_useful_task=cost.cost_per_useful_task(session, date_from, date_to),
    )


@router.get("/admin/llm/recent")
def llm_recent(
    session: Annotated[Session, Depends(get_session)],
    _user: _ReadUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, list[dict[str, Any]]]:
    """The most expensive recent calls (for spotting runaways)."""
    return {"items": cost.recent_calls(session, limit=limit)}


# ── budget ────────────────────────────────────────────────────────────────────


class BudgetRead(BaseModel):
    period: str
    limit_usd: Decimal | None
    alert_pct: int
    spent_usd: Decimal
    pct: float | None


class BudgetPatch(BaseModel):
    period: str | None = None  # None → the 'default' fallback row
    limit_usd: Decimal
    alert_pct: int = 80


@router.get("/admin/llm/budget", response_model=BudgetRead)
def get_budget(session: Annotated[Session, Depends(get_session)], _user: _ReadUser) -> BudgetRead:
    return BudgetRead(**cost.budget_status(session))


@router.patch("/admin/llm/budget", response_model=BudgetRead)
def patch_budget(
    body: BudgetPatch,
    session: Annotated[Session, Depends(get_session)],
    user: _AdminUser,
) -> BudgetRead:
    """Upsert a budget row; writes a reversible threshold_change decision."""
    period = body.period or "default"
    old = session.execute(
        text("SELECT limit_usd, alert_pct FROM app.llm_budget WHERE period = :p"),
        {"p": period},
    ).one_or_none()
    session.execute(
        text(
            "INSERT INTO app.llm_budget (period, limit_usd, alert_pct) "
            "VALUES (:p, :limit, :pct) "
            "ON CONFLICT (period) DO UPDATE SET limit_usd = :limit, alert_pct = :pct"
        ),
        {"p": period, "limit": body.limit_usd, "pct": body.alert_pct},
    )
    log_decision(
        session,
        kind="threshold_change",
        actor="user",
        summary=f"LLM budžet za {period} postavljen na {body.limit_usd} USD ({body.alert_pct}%)",
        payload={
            "period": period,
            "old": {"limit_usd": str(old.limit_usd), "alert_pct": old.alert_pct} if old else None,
            "new": {"limit_usd": str(body.limit_usd), "alert_pct": body.alert_pct},
            "changed_by": user.id,
        },
    )
    session.commit()
    return BudgetRead(**cost.budget_status(session, period))


# ── pricing ───────────────────────────────────────────────────────────────────


class PricingRow(BaseModel):
    model: str
    input_per_mtok: Decimal
    output_per_mtok: Decimal
    cache_read_per_mtok: Decimal | None
    batch_discount: Decimal


@router.get("/admin/llm/pricing")
def get_pricing(
    session: Annotated[Session, Depends(get_session)], _user: _ReadUser
) -> dict[str, list[PricingRow]]:
    rows = session.execute(
        text(
            "SELECT model, input_per_mtok, output_per_mtok, cache_read_per_mtok, batch_discount "
            "FROM app.llm_pricing ORDER BY model"
        )
    ).all()
    return {"items": [PricingRow(**row._mapping) for row in rows]}


@router.patch("/admin/llm/pricing", response_model=PricingRow)
def patch_pricing(
    body: PricingRow,
    session: Annotated[Session, Depends(get_session)],
    user: _AdminUser,
) -> PricingRow:
    """Edit a model's prices; writes a reversible threshold_change decision."""
    old = session.execute(
        text(
            "SELECT input_per_mtok, output_per_mtok, cache_read_per_mtok, batch_discount "
            "FROM app.llm_pricing WHERE model = :m"
        ),
        {"m": body.model},
    ).one_or_none()
    if old is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": f"Nema cijene za model {body.model}"},
        )
    session.execute(
        text(
            "UPDATE app.llm_pricing SET input_per_mtok = :i, output_per_mtok = :o, "
            "cache_read_per_mtok = :c, batch_discount = :b WHERE model = :m"
        ),
        {
            "m": body.model,
            "i": body.input_per_mtok,
            "o": body.output_per_mtok,
            "c": body.cache_read_per_mtok,
            "b": body.batch_discount,
        },
    )
    log_decision(
        session,
        kind="threshold_change",
        actor="user",
        summary=f"Cijena modela {body.model} izmijenjena",
        payload={
            "model": body.model,
            "old": {
                "input_per_mtok": str(old.input_per_mtok),
                "output_per_mtok": str(old.output_per_mtok),
            },
            "new": {
                "input_per_mtok": str(body.input_per_mtok),
                "output_per_mtok": str(body.output_per_mtok),
            },
            "changed_by": user.id,
        },
    )
    session.commit()
    return body
