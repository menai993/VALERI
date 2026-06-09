"""Rep activity logging + rollups (C-CRM2).

Activities are VALERI-native user data (no LLM); every rollup figure is a SQL
COUNT. RBAC row scope is the rep's own customers/activities (the C-CRM1 pattern).
"""

import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.crm.models import Activity
from valeri_api.crm.probability import ACTIVITY_KINDS
from valeri_api.crm.schemas import ActivityRead, RepActivityBlock, RepActivityRow


def log_activity(
    session: Session,
    *,
    sales_rep_id: int,
    kind: str,
    customer_id: int | None = None,
    done: bool = False,
    at: datetime.datetime | None = None,
) -> ActivityRead:
    """Record one activity (meeting/call/offer/follow_up/analysis)."""
    activity = Activity(
        sales_rep_id=sales_rep_id,
        kind=kind,
        customer_id=customer_id,
        done=done,
        at=at,
    )
    session.add(activity)
    session.flush()
    session.refresh(activity)
    return ActivityRead.model_validate(activity)


def rep_activity_rollup(
    session: Session,
    as_of: datetime.date,
    sales_rep_id: int | None = None,
) -> RepActivityBlock:
    """Per-rep activity rollup for the month of `as_of`: counts by kind + completion.

    `sales_rep_id` limits the rollup to one rep (a rep viewing their own); None = all reps.
    Every number is a SQL COUNT — never computed by a model.
    """
    params: dict[str, Any] = {"as_of": as_of}
    rep_filter = ""
    if sales_rep_id is not None:
        rep_filter = " AND a.sales_rep_id = :rep_id"
        params["rep_id"] = sales_rep_id

    # Counts by (rep, kind) + done, for activities in the month of as_of.
    rows = session.execute(
        text(
            "SELECT sr.id AS sales_rep_id, sr.name, a.kind, "
            "       COUNT(*) AS count, "
            "       COUNT(*) FILTER (WHERE a.done) AS done "
            "FROM core.sales_rep sr "
            "JOIN app.activity a ON a.sales_rep_id = sr.id "
            "WHERE date_trunc('month', a.at) = date_trunc('month', CAST(:as_of AS date))"
            + rep_filter
            + " GROUP BY sr.id, sr.name, a.kind ORDER BY sr.id"
        ),
        params,
    ).all()

    # Fold (rep, kind) rows into one row per rep.
    reps: dict[int, dict[str, Any]] = {}
    for row in rows:
        rep = reps.setdefault(
            row.sales_rep_id,
            {"name": row.name, "total": 0, "done": 0, "by_kind": dict.fromkeys(ACTIVITY_KINDS, 0)},
        )
        rep["total"] += row.count
        rep["done"] += row.done
        rep["by_kind"][row.kind] = rep["by_kind"].get(row.kind, 0) + row.count

    rep_rows = [
        RepActivityRow(
            sales_rep_id=rep_id,
            name=data["name"],
            total=data["total"],
            done=data["done"],
            completion=(f"{data['done'] / data['total']:.4f}" if data["total"] else "0.0000"),
            by_kind=data["by_kind"],
        )
        for rep_id, data in sorted(reps.items())
    ]
    return RepActivityBlock(as_of=as_of, reps=rep_rows)
