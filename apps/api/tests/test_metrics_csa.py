"""CSA Phase 1 golden tests: the new ranking/catalog metrics equal hand-computed
values from the M3 golden fixture, to the unit. Written BEFORE the registry SQL
(TDD); expected values are computed by hand from tests/fixtures/metrics_fixture.py,
never copied from SQL output.

Period used: (2025-10-03, 2026-06-01] — half-open, covers every fixture invoice
(earliest 2025-10-04, latest 2026-06-01).

Hand computation (line_total per article over the full period):
  A1 (TST-A1, papir): 100+150+40+100+200+500+990+10+30 = 2120.00  qty 212.000
  A2 (TST-A2, papir): 100+200+40+60+200+40             =  640.00  qty  32.000
  A3 (TST-A3, hemija): 110+22+55                        =  187.00  qty  34.000
  A4 (TST-A4, hemija): 100                              =  100.00  qty   1.000
  category papir = 2120+640 = 2760.00 ; hemija = 187+100 = 287.00
  customer C1 = 2590.00 ; C2 = 417.00 ; C5 = 30.00 ; C3 = 10.00
  restoran segment (C2,C5 only): A2 340.00, A3 77.00, A1 30.00
"""

import datetime
from decimal import Decimal

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from tests.fixtures import metrics_fixture as fx
from valeri_api.semantic.query_builder import run_metric

D = Decimal
PERIOD = {"from_date": datetime.date(2025, 10, 3), "to_date": datetime.date(2026, 6, 1)}


@pytest.fixture(scope="module")
def csa_db(db_engine: Engine, seed_data):
    """Load the golden fixture; restore the M1 seed for other modules on teardown."""
    with Session(db_engine) as session:
        fx.load_fixture(session)
        session.commit()
    yield db_engine
    from valeri_api.seed.loader import load, reset

    with Session(db_engine) as session:
        reset(session)
        load(seed_data, session)
        session.commit()


def _rows(engine: Engine, metric: str, params: dict) -> list[dict]:
    with Session(engine) as session:
        return run_metric(session, metric, params).rows


# ── top_articles ─────────────────────────────────────────────────────────────


def test_top_articles_full_period_ranked_by_revenue(csa_db: Engine) -> None:
    rows = _rows(csa_db, "top_articles", PERIOD)
    assert [(r["code"], r["revenue"], r["qty"]) for r in rows] == [
        ("TST-A1", D("2120.00"), D("212.000")),
        ("TST-A2", D("640.00"), D("32.000")),
        ("TST-A3", D("187.00"), D("34.000")),
        ("TST-A4", D("100.00"), D("1.000")),
    ]


def test_top_articles_limit(csa_db: Engine) -> None:
    rows = _rows(csa_db, "top_articles", {**PERIOD, "limit": 2})
    assert [r["code"] for r in rows] == ["TST-A1", "TST-A2"]


def test_top_articles_by_category(csa_db: Engine) -> None:
    rows = _rows(csa_db, "top_articles", {**PERIOD, "category_id": 2})  # hemija
    assert [(r["code"], r["revenue"]) for r in rows] == [
        ("TST-A3", D("187.00")),
        ("TST-A4", D("100.00")),
    ]


def test_top_articles_by_segment(csa_db: Engine) -> None:
    rows = _rows(csa_db, "top_articles", {**PERIOD, "segment": "restoran"})
    assert [(r["code"], r["revenue"]) for r in rows] == [
        ("TST-A2", D("340.00")),
        ("TST-A3", D("77.00")),
        ("TST-A1", D("30.00")),
    ]


# ── category_sales ───────────────────────────────────────────────────────────


def test_category_sales(csa_db: Engine) -> None:
    rows = _rows(csa_db, "category_sales", PERIOD)
    assert [(r["category"], r["revenue"]) for r in rows] == [
        ("papir", D("2760.00")),
        ("hemija", D("287.00")),
    ]


# ── top_customers ────────────────────────────────────────────────────────────


def test_top_customers(csa_db: Engine) -> None:
    rows = _rows(csa_db, "top_customers", PERIOD)
    assert [(r["customer_name"], r["revenue"]) for r in rows] == [
        ("Hotel Alfa", D("2590.00")),
        ("Restoran Beta", D("417.00")),
        ("Restoran Epsilon", D("30.00")),
        ("Kafić Gama", D("10.00")),
    ]


# ── article_catalog ──────────────────────────────────────────────────────────


def test_article_catalog_lists_active_articles_with_category(csa_db: Engine) -> None:
    rows = _rows(csa_db, "article_catalog", {})
    assert [(r["code"], r["name"], r["category"]) for r in rows] == [
        ("TST-A1", "Papir A", "papir"),
        ("TST-A2", "Papir B", "papir"),
        ("TST-A3", "Hemija C", "hemija"),
        ("TST-A4", "Hemija D", "hemija"),
    ]


def test_article_catalog_filtered_by_category(csa_db: Engine) -> None:
    rows = _rows(csa_db, "article_catalog", {"category_id": 2})
    assert [r["code"] for r in rows] == ["TST-A3", "TST-A4"]
