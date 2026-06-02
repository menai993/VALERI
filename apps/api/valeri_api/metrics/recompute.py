"""Recompute job for the derived metric tables (full refresh, one transaction).

Python orchestrates only: it reads the .sql files, binds :as_of, and executes.
Every number is produced inside PostgreSQL.
"""

import datetime
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

SQL_DIR = Path(__file__).resolve().parent / "sql"

# (target table, sql file) in recompute order.
_TABLES = [
    ("core.customer_metrics", "customer_metrics.sql"),
    ("core.cust_article_cadence", "cust_article_cadence.sql"),
    ("core.segment_basket", "segment_basket.sql"),
]


class RecomputeResult(BaseModel):
    """What a recompute run produced (row counts per table)."""

    as_of: datetime.date
    rows: dict[str, int]


def recompute_all(session: Session, as_of: datetime.date | None = None) -> RecomputeResult:
    """Full refresh of all three derived tables for the given reference date.

    DELETE + INSERT … SELECT inside the caller's transaction: either everything
    is recomputed consistently or nothing changes.
    """
    reference_date = as_of or datetime.date.today()
    rows: dict[str, int] = {}

    for table, sql_file in _TABLES:
        statement = (SQL_DIR / sql_file).read_text(encoding="utf-8")
        session.execute(text(f"DELETE FROM {table}"))  # noqa: S608 - fixed internal table list
        result = session.execute(text(statement), {"as_of": reference_date})
        rows[table] = result.rowcount

    session.flush()
    return RecomputeResult(as_of=reference_date, rows=rows)
