"""CI2 behavioral-expectation model: every figure equals independent SQL.

core.client_expectation is recomputed by SQL from core.customer_metrics; the LLM
computes nothing here. We recompute over the M1 seed and check the formula
(expected interval, gap, stretch ratio, early-decline flag) per customer.
"""

import datetime
from decimal import ROUND_HALF_UP, Decimal

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session


@pytest.fixture(scope="module")
def expectations_db(seeded_db: Engine):
    """Recompute the derived tables (incl. client_expectation) over the seed."""
    from valeri_api.metrics.recompute import recompute_all

    as_of = datetime.date.today()
    with Session(seeded_db) as session:
        recompute_all(session, as_of=as_of)
        session.commit()
    return seeded_db, as_of


@pytest.mark.anyio
async def test_expectation_numbers_match_sql(expectations_db) -> None:
    engine, as_of = expectations_db
    with engine.connect() as conn:
        early_stretch = Decimal(
            str(
                conn.execute(
                    text(
                        "SELECT (value::text)::numeric FROM app.rule_config "
                        "WHERE rule = 'client_expectation' AND param = 'early_decline_stretch'"
                    )
                ).scalar()
            )
        )
        rows = conn.execute(
            text(
                "SELECT ce.customer_id, ce.expected_interval_d, ce.gap_days, ce.stretch_ratio, "
                "       ce.early_decline, m.avg_order_interval_d, m.last_order_date "
                "FROM core.client_expectation ce "
                "JOIN core.customer_metrics m ON m.customer_id = ce.customer_id "
                "ORDER BY ce.customer_id"
            )
        ).all()

    assert rows, "the recompute populated client_expectation for the seed"
    saw_early_decline = False

    for row in rows:
        # expected interval mirrors the customer's metric, verbatim.
        assert row.expected_interval_d == row.avg_order_interval_d

        if row.last_order_date is None:
            continue
        expected_gap = (as_of - row.last_order_date).days
        assert row.gap_days == expected_gap

        if row.avg_order_interval_d and row.avg_order_interval_d > 0:
            expected_stretch = (Decimal(expected_gap) / row.avg_order_interval_d).quantize(
                Decimal("0.001"), rounding=ROUND_HALF_UP
            )
            assert row.stretch_ratio == expected_stretch
            assert row.early_decline == (expected_stretch >= early_stretch)
            saw_early_decline = saw_early_decline or row.early_decline

    # The seed plants sleeping customers (large gap) → at least one early-decline sign.
    assert saw_early_decline, "planted sleeping customers should flag early_decline"
