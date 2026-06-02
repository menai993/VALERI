"""M3 golden tests: every metric's SQL output equals hand-computed fixtures exactly.

Trust-critical (TDD): these tests were written before the metrics implementation.
The expected values come from tests/fixtures/metrics_fixture.py and were computed
by hand — never copied from SQL output.
"""

import datetime
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tests.fixtures import metrics_fixture as fx

# ── fixtures ─────────────────────────────────────────────────────────────────


def _restore_m1_seed(engine: Engine, seed_data) -> None:
    from valeri_api.seed.loader import load, reset

    with Session(engine) as session:
        reset(session)
        load(seed_data, session)
        session.commit()


@pytest.fixture(scope="module")
def golden_db(db_engine: Engine, seed_data):
    """Load the golden fixture, run the recompute with the fixed AS_OF, yield the engine.

    Teardown restores the M1 seed for other test modules.
    """
    from valeri_api.metrics.recompute import recompute_all

    with Session(db_engine) as session:
        fx.load_fixture(session)
        recompute_all(session, as_of=fx.AS_OF)
        session.commit()

    yield db_engine

    _restore_m1_seed(db_engine, seed_data)


def _fetch_customer_metrics(engine: Engine) -> dict[int, dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT customer_id, turnover_60d, turnover_6m_avg_60d, last_order_date, "
                "avg_order_interval_d, segment FROM core.customer_metrics ORDER BY customer_id"
            )
        ).all()
    return {
        row.customer_id: {
            "turnover_60d": row.turnover_60d,
            "turnover_6m_avg_60d": row.turnover_6m_avg_60d,
            "last_order_date": row.last_order_date,
            "avg_order_interval_d": row.avg_order_interval_d,
            "segment": row.segment,
        }
        for row in rows
    }


# ── golden tests ─────────────────────────────────────────────────────────────


def test_golden_customer_metrics(golden_db: Engine) -> None:
    """Every core.customer_metrics row equals the hand-computed expectation exactly."""
    actual = _fetch_customer_metrics(golden_db)

    assert set(actual) == set(fx.EXPECTED_CUSTOMER_METRICS), "row set differs"
    for customer_id, expected in fx.EXPECTED_CUSTOMER_METRICS.items():
        for column, expected_value in expected.items():
            actual_value = actual[customer_id][column]
            assert (
                actual_value == expected_value
            ), f"customer {customer_id}.{column}: {actual_value!r} != {expected_value!r}"


def test_golden_cadence(golden_db: Engine) -> None:
    """Every core.cust_article_cadence row equals the hand-computed expectation exactly."""
    with golden_db.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT customer_id, article_id, avg_interval_d, last_seen "
                "FROM core.cust_article_cadence ORDER BY customer_id, article_id"
            )
        ).all()

    actual = {
        (row.customer_id, row.article_id): {
            "avg_interval_d": row.avg_interval_d,
            "last_seen": row.last_seen,
        }
        for row in rows
    }
    assert set(actual) == set(fx.EXPECTED_CADENCE), "cadence pair set differs"
    for pair, expected in fx.EXPECTED_CADENCE.items():
        assert (
            actual[pair]["avg_interval_d"] == expected["avg_interval_d"]
        ), f"{pair} interval: {actual[pair]['avg_interval_d']} != {expected['avg_interval_d']}"
        assert (
            actual[pair]["last_seen"] == expected["last_seen"]
        ), f"{pair} last_seen: {actual[pair]['last_seen']} != {expected['last_seen']}"


def test_golden_segment_basket(golden_db: Engine) -> None:
    """Every core.segment_basket row equals the hand-computed prevalence exactly."""
    with golden_db.connect() as conn:
        rows = conn.execute(
            text("SELECT segment, category_id, prevalence FROM core.segment_basket")
        ).all()

    actual = {(row.segment, row.category_id): row.prevalence for row in rows}
    assert actual == fx.EXPECTED_SEGMENT_BASKET


def test_window_boundaries_are_half_open(golden_db: Engine) -> None:
    """Boundary invoices land in the correct window: (start, end] semantics.

    Invoice 4 (exactly as_of-60d) must be in the baseline, NOT the 60d window;
    invoice 3 (exactly as_of) must be in the 60d window; invoice 10 (exactly
    as_of-240d) must be outside both.
    """
    metrics = _fetch_customer_metrics(golden_db)[1]
    # 60d window: 210+150+40 = 400.00. If invoice 4 (100.00) leaked in → 500.00.
    assert metrics["turnover_60d"] == Decimal("400.00")
    # Baseline: 1200.00/3 = 400.00. If invoice 10 (990.00) leaked in → 730.00;
    # if invoice 4 (100.00) were excluded → 366.67.
    assert metrics["turnover_6m_avg_60d"] == Decimal("400.00")


def test_recompute_is_idempotent(golden_db: Engine) -> None:
    """Running the recompute twice produces identical tables."""
    from valeri_api.metrics.recompute import recompute_all

    before = _fetch_customer_metrics(golden_db)
    with Session(golden_db) as session:
        recompute_all(session, as_of=fx.AS_OF)
        session.commit()
    after = _fetch_customer_metrics(golden_db)
    assert before == after


def test_recompute_covers_every_customer(golden_db: Engine) -> None:
    """Every customer has a customer_metrics row — even with zero invoices (C4)."""
    with golden_db.connect() as conn:
        missing = conn.execute(
            text(
                "SELECT c.id FROM core.customer c "
                "LEFT JOIN core.customer_metrics m ON m.customer_id = c.id "
                "WHERE m.customer_id IS NULL"
            )
        ).all()
    assert missing == [], f"customers without metrics row: {[r[0] for r in missing]}"


# ── seed-consistency tests ───────────────────────────────────────────────────


@pytest.fixture(scope="module")
def seeded_metrics_db(db_engine: Engine, seed_data):
    """M1 seed loaded + metrics recomputed with the manifest's as_of."""
    from valeri_api.metrics.recompute import recompute_all
    from valeri_api.seed.loader import load, reset

    as_of = datetime.date.fromisoformat(seed_data.manifest["as_of"])
    with Session(db_engine) as session:
        reset(session)
        load(seed_data, session)
        recompute_all(session, as_of=as_of)
        session.commit()
    return db_engine, as_of


def test_seed_customer_metrics_match_direct_sql(seeded_metrics_db, seed_data) -> None:
    """Cross-check: every customer's stored metrics equal an independent direct SQL computation."""
    engine, as_of = seeded_metrics_db
    with engine.connect() as conn:
        mismatches = conn.execute(
            text("""
                WITH direct AS (
                  SELECT c.id AS customer_id,
                         COALESCE(SUM(i.total) FILTER (
                           WHERE i.date > CAST(:as_of AS date) - 60
                             AND i.date <= CAST(:as_of AS date)), 0) AS turnover_60d,
                         COALESCE(SUM(i.total) FILTER (
                           WHERE i.date > CAST(:as_of AS date) - 240
                             AND i.date <= CAST(:as_of AS date) - 60), 0) / 3 AS baseline,
                         MAX(i.date) AS last_order_date
                  FROM core.customer c
                  LEFT JOIN core.invoice i ON i.customer_id = c.id
                  GROUP BY c.id
                )
                SELECT d.customer_id
                FROM direct d
                JOIN core.customer_metrics m ON m.customer_id = d.customer_id
                WHERE m.turnover_60d <> ROUND(d.turnover_60d, 2)
                   OR m.turnover_6m_avg_60d <> ROUND(d.baseline, 2)
                   OR m.last_order_date IS DISTINCT FROM d.last_order_date
                """),
            {"as_of": as_of},
        ).all()
    assert mismatches == [], f"metrics differ from direct SQL for customers {mismatches}"


def test_seed_planted_declines_visible(seeded_metrics_db, seed_data) -> None:
    """The 3 planted declines (and 2 seasonal cafés) show a low 60d/baseline ratio."""
    engine, _ = seeded_metrics_db
    manifest = seed_data.manifest

    with engine.connect() as conn:
        for case in manifest["declines"]:
            row = conn.execute(
                text(
                    "SELECT turnover_60d, turnover_6m_avg_60d FROM core.customer_metrics "
                    "WHERE customer_id = :cid"
                ),
                {"cid": case["customer_id"]},
            ).one()
            ratio = float(row.turnover_60d) / float(row.turnover_6m_avg_60d)
            assert 0.30 <= ratio <= 0.65, f"decline {case['customer_id']}: ratio {ratio:.2f}"

        for case in manifest["seasonal_cafes"]:
            row = conn.execute(
                text(
                    "SELECT turnover_60d, turnover_6m_avg_60d FROM core.customer_metrics "
                    "WHERE customer_id = :cid"
                ),
                {"cid": case["customer_id"]},
            ).one()
            ratio = float(row.turnover_60d) / float(row.turnover_6m_avg_60d)
            assert ratio <= 0.75, f"seasonal café {case['customer_id']}: ratio {ratio:.2f}"


def test_recompute_after_import(db_engine: Engine, seed_data, tmp_path) -> None:
    """A fresh M2 import with recompute_metrics=True leaves the metric tables populated."""
    from valeri_api.ingest.pipeline import run_import
    from valeri_api.seed.export import write_export_csvs
    from valeri_api.seed.loader import reset

    export_dir = tmp_path / "export"
    write_export_csvs(seed_data, export_dir)
    files = {name: export_dir / f"{name}.csv" for name in ("kupci", "artikli", "fakture", "stavke")}

    with Session(db_engine) as session:
        reset(session)
        session.commit()
    with Session(db_engine) as session:
        run_import(session, files, source="test-metrics-import", recompute_metrics=True)
        session.commit()

    with db_engine.connect() as conn:
        n_metrics = conn.execute(text("SELECT COUNT(*) FROM core.customer_metrics")).scalar()
        n_customers = conn.execute(text("SELECT COUNT(*) FROM core.customer")).scalar()
        n_cadence = conn.execute(text("SELECT COUNT(*) FROM core.cust_article_cadence")).scalar()
    assert n_metrics == n_customers
    assert n_cadence > 0

    _restore_m1_seed(db_engine, seed_data)
