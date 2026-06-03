"""CSA Phase 3: the SQL safety gate for self-proposed metrics.

The wall that makes human approval safe. Static checks need no DB; the EXPLAIN
check uses a real session (rolled back).
"""

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from valeri_api.semantic.proposal_safety import UnsafeMetricSQL, validate_metric_sql

# A known-good, read-only, bind-param SELECT (mirrors the registry style).
_GOOD = (
    "SELECT a.id AS article_id, COALESCE(SUM(l.line_total), 0) AS revenue "
    "FROM core.invoice_line l "
    "JOIN core.invoice i ON i.id = l.invoice_id "
    "JOIN core.article a ON a.id = l.article_id "
    "WHERE i.date > :from_date AND i.date <= :to_date "
    "GROUP BY a.id"
)
_GOOD_PARAMS = {"from_date", "to_date"}


def test_accepts_good_select_static() -> None:
    validate_metric_sql(_GOOD, _GOOD_PARAMS)  # no session → static checks only; must not raise


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO core.article (code) VALUES ('x')",
        "UPDATE core.article SET active = false",
        "DELETE FROM core.invoice",
        "DROP TABLE core.invoice",
        "TRUNCATE core.invoice",
        "SELECT 1; DROP TABLE core.invoice",  # multi-statement
        "SELECT * FROM core.invoice; SELECT 1;",  # multi-statement
        "WITH x AS (SELECT 1) SELECT * FROM x",  # not a bare SELECT
        "SELECT * FROM pg_catalog.pg_user",  # disallowed schema
        "SELECT * FROM staging.kupci",  # disallowed schema
        "SELECT * FROM invoice",  # unqualified table
        "SELECT line_total FROM core.invoice_line -- sneaky",  # comment
        "SELECT line_total FROM core.invoice_line /* c */",  # comment
        "SELECT format('%s', x) FROM core.invoice",  # interpolation token
    ],
)
def test_rejects_unsafe_sql(sql: str) -> None:
    with pytest.raises(UnsafeMetricSQL):
        validate_metric_sql(sql, _GOOD_PARAMS)


def test_rejects_undeclared_bind_param() -> None:
    with pytest.raises(UnsafeMetricSQL):
        validate_metric_sql(
            "SELECT 1 FROM core.invoice WHERE customer_id = :customer_id", {"from_date"}
        )


# ── EXPLAIN check (needs a DB) ────────────────────────────────────────────────


def test_explain_accepts_valid_query(db_session: Session) -> None:
    validate_metric_sql(_GOOD, _GOOD_PARAMS, session=db_session)  # must not raise


def test_explain_rejects_invalid_column(db_session: Session) -> None:
    bad = "SELECT nonexistent_col FROM core.invoice WHERE id = :id"
    with pytest.raises(UnsafeMetricSQL):
        validate_metric_sql(bad, {"id"}, session=db_session)
