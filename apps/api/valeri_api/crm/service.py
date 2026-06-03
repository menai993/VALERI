"""Opportunity CRUD + the SQL pipeline aggregation (C-CRM1).

Every pipeline figure is SQL-computed: the effective probability is
`COALESCE(o.probability, stage_default)` joined against the rule_config map, and the
weighted value / conversion rate are SQL aggregates over it. The API never returns a
number this module didn't compute in SQL — tests assert API == an independent query.

RBAC row scope (`customer_ids`): None = unrestricted (owner/admin/finance); a set =
a sales rep's own customers (fail closed).
"""

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.audit.serialization import jsonable
from valeri_api.crm.models import Opportunity, OpportunityStageHistory
from valeri_api.crm.probability import ALL_STAGES, OPEN_STAGES
from valeri_api.crm.schemas import (
    OpportunityRead,
    OpportunitySummary,
    OpportunitySummaryRow,
    PipelineResponse,
    PipelineStage,
)


class OpportunityNotFound(LookupError):
    """The referenced opportunity does not exist."""


# A single source of truth for the effective probability: the opportunity's own
# probability, else the stage default from rule_config (rule='crm'). Reused by
# every read/aggregate so the API and tests can never disagree with the DB.
_EFFECTIVE_PROB_SQL = (
    "COALESCE(o.probability, "
    "(SELECT (value->>o.stage::text)::numeric "
    " FROM app.rule_config WHERE rule = 'crm' AND param = 'stage_probability'))"
)

_OPPORTUNITY_SELECT = f"""
SELECT o.id, o.customer_id, c.name AS customer_name, o.title,
       o.value::text AS value, o.probability::text AS probability,
       o.stage, o.source, o.expected_close, o.owner_rep_id, sr.name AS owner_rep_name,
       {_EFFECTIVE_PROB_SQL}::text AS effective_probability,
       (o.value * {_EFFECTIVE_PROB_SQL})::numeric(14,2)::text AS weighted_value,
       o.created_at
FROM app.opportunity o
LEFT JOIN core.customer c ON c.id = o.customer_id
LEFT JOIN core.sales_rep sr ON sr.id = o.owner_rep_id
"""


def _scope_clause(customer_ids: set[int] | None) -> tuple[str, dict[str, Any]]:
    """RBAC row scope: None → all; a set → only those customers (fail closed)."""
    if customer_ids is None:
        return "", {}
    if not customer_ids:
        return " AND false", {}  # a rep with no customers sees nothing
    return " AND o.customer_id = ANY(:customer_ids)", {"customer_ids": sorted(customer_ids)}


def _read(row: Any) -> OpportunityRead:
    return OpportunityRead(**jsonable(dict(row)))


# ── reads ───────────────────────────────────────────────────────────────────────


def list_opportunities(
    session: Session,
    customer_ids: set[int] | None,
    stage: str | None = None,
    customer_id: int | None = None,
) -> list[OpportunityRead]:
    clause, params = _scope_clause(customer_ids)
    if stage is not None:
        clause += " AND o.stage = :stage"
        params["stage"] = stage
    if customer_id is not None:
        clause += " AND o.customer_id = :only_customer"
        params["only_customer"] = customer_id
    rows = session.execute(
        text(_OPPORTUNITY_SELECT + " WHERE true" + clause + " ORDER BY o.id DESC"), params
    ).mappings()
    return [_read(row) for row in rows]


def get_opportunity(session: Session, opportunity_id: int) -> OpportunityRead:
    row = (
        session.execute(text(_OPPORTUNITY_SELECT + " WHERE o.id = :id"), {"id": opportunity_id})
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise OpportunityNotFound(f"Prilika {opportunity_id} ne postoji")
    return _read(row)


def pipeline(session: Session, customer_ids: set[int] | None) -> PipelineResponse:
    """Kanban columns + weighted value + conversion — all SQL."""
    clause, params = _scope_clause(customer_ids)

    # Per-stage aggregates (count, raw value, weighted value).
    agg_rows = {
        row.stage: row
        for row in session.execute(
            text(
                f"SELECT o.stage, COUNT(*) AS count, "
                f"COALESCE(SUM(o.value), 0)::numeric(14,2)::text AS value, "
                f"COALESCE(SUM(o.value * {_EFFECTIVE_PROB_SQL}), 0)::numeric(14,2)::text "
                f"AS weighted_value "
                f"FROM app.opportunity o WHERE true{clause} GROUP BY o.stage"
            ),
            params,
        )
    }
    by_stage: dict[str, list[OpportunityRead]] = {stage: [] for stage in ALL_STAGES}
    for opp in list_opportunities(session, customer_ids):
        by_stage.setdefault(opp.stage, []).append(opp)

    stages = [
        PipelineStage(
            stage=stage,
            count=getattr(agg_rows.get(stage), "count", 0) or 0,
            value=getattr(agg_rows.get(stage), "value", "0.00") or "0.00",
            weighted_value=getattr(agg_rows.get(stage), "weighted_value", "0.00") or "0.00",
            opportunities=by_stage.get(stage, []),
        )
        for stage in ALL_STAGES
    ]

    total_weighted = session.execute(
        text(
            f"SELECT COALESCE(SUM(o.value * {_EFFECTIVE_PROB_SQL}), 0)::numeric(14,2)::text "
            f"FROM app.opportunity o WHERE o.stage = ANY(:open_stages){clause}"
        ),
        {**params, "open_stages": list(OPEN_STAGES)},
    ).scalar()

    conversion = _conversion_rate(session, customer_ids)
    open_count = session.execute(
        text(
            f"SELECT COUNT(*) FROM app.opportunity o " f"WHERE o.stage = ANY(:open_stages){clause}"
        ),
        {**params, "open_stages": list(OPEN_STAGES)},
    ).scalar()

    return PipelineResponse(
        stages=stages,
        total_weighted_value=total_weighted,
        conversion_rate=conversion,
        open_count=open_count,
    )


def _conversion_rate(session: Session, customer_ids: set[int] | None) -> str:
    """won / (won + lost) over closed opportunities; '0.0000' when none closed."""
    clause, params = _scope_clause(customer_ids)
    row = session.execute(
        text(
            f"SELECT COUNT(*) FILTER (WHERE o.stage = 'won') AS won, "
            f"COUNT(*) FILTER (WHERE o.stage IN ('won','lost')) AS closed "
            f"FROM app.opportunity o WHERE true{clause}"
        ),
        params,
    ).one()
    if not row.closed:
        return "0.0000"
    return f"{row.won / row.closed:.4f}"


def dashboard_summary(session: Session, customer_ids: set[int] | None) -> OpportunitySummary:
    """The dashboard 'Prilike' block: open count, conversion, weighted value, top deals."""
    clause, params = _scope_clause(customer_ids)

    open_count = session.execute(
        text(
            f"SELECT COUNT(*) FROM app.opportunity o " f"WHERE o.stage = ANY(:open_stages){clause}"
        ),
        {**params, "open_stages": list(OPEN_STAGES)},
    ).scalar()
    weighted = session.execute(
        text(
            f"SELECT COALESCE(SUM(o.value * {_EFFECTIVE_PROB_SQL}), 0)::numeric(14,2)::text "
            f"FROM app.opportunity o WHERE o.stage = ANY(:open_stages){clause}"
        ),
        {**params, "open_stages": list(OPEN_STAGES)},
    ).scalar()

    top_rows = session.execute(
        text(
            f"SELECT o.id, o.title, c.name AS customer_name, o.value::text AS value, "
            f"o.probability::text AS probability, "
            f"(o.value * {_EFFECTIVE_PROB_SQL})::numeric(14,2)::text AS weighted_value "
            f"FROM app.opportunity o LEFT JOIN core.customer c ON c.id = o.customer_id "
            f"WHERE o.stage = ANY(:open_stages){clause} "
            f"ORDER BY (o.value * {_EFFECTIVE_PROB_SQL}) DESC NULLS LAST LIMIT 5"
        ),
        {**params, "open_stages": list(OPEN_STAGES)},
    ).mappings()

    return OpportunitySummary(
        open_count=open_count,
        conversion_rate=_conversion_rate(session, customer_ids),
        weighted_value=weighted,
        top=[OpportunitySummaryRow(**jsonable(dict(row))) for row in top_rows],
    )


# ── writes (RBAC enforced by the caller; stage history append here) ───────────────


def create_opportunity(
    session: Session,
    *,
    customer_id: int,
    title: str,
    stage: str = "lead",
    value: float | None = None,
    probability: float | None = None,
    source: str | None = None,
    expected_close: Any = None,
    owner_rep_id: int | None = None,
) -> OpportunityRead:
    """Create an opportunity + its initial stage_history row."""
    opportunity = Opportunity(
        customer_id=customer_id,
        title=title,
        value=value,
        probability=probability,
        stage=stage,
        source=source,
        expected_close=expected_close,
        owner_rep_id=owner_rep_id,
    )
    session.add(opportunity)
    session.flush()
    session.add(OpportunityStageHistory(opportunity_id=opportunity.id, stage=stage))
    session.flush()
    return get_opportunity(session, opportunity.id)


def update_opportunity(
    session: Session, opportunity_id: int, changes: dict[str, Any]
) -> OpportunityRead:
    """Patch an opportunity; a stage change appends a stage_history row (append-only)."""
    opportunity = session.get(Opportunity, opportunity_id)
    if opportunity is None:
        raise OpportunityNotFound(f"Prilika {opportunity_id} ne postoji")

    new_stage = changes.get("stage")
    stage_changed = new_stage is not None and new_stage != opportunity.stage

    for field, value in changes.items():
        setattr(opportunity, field, value)
    session.flush()

    if stage_changed:
        session.add(OpportunityStageHistory(opportunity_id=opportunity.id, stage=new_stage))
        session.flush()

    return get_opportunity(session, opportunity_id)
