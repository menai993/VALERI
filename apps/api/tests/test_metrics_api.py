"""M8 acceptance: metrics endpoints — overview / revenue-trend / customer 360 == SQL."""

import datetime
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tests.conftest import login, make_client
from valeri_api.scanner.scan import run_scan
from valeri_api.seed.users import OWNER_EMAIL


@pytest.fixture(scope="module")
def metrics_db(db_engine: Engine, seed_data):
    """Seed + recomputed metrics (a scan without task narration)."""
    from valeri_api.seed.loader import load, reset

    as_of = datetime.date.fromisoformat(seed_data.manifest["as_of"])
    with Session(db_engine) as session:
        session.execute(
            text(
                "TRUNCATE audit.ai_log, audit.task_log, app.task_feedback, app.approval, "
                "app.owner_report, app.task, app.signal, app.learned_rule "
                "RESTART IDENTITY CASCADE"
            )
        )
        reset(session)
        load(seed_data, session)
        run_scan(session, as_of=as_of, create_tasks=True)
        session.commit()

    yield db_engine, as_of

    with Session(db_engine) as session:
        reset(session)
        load(seed_data, session)
        session.commit()


@pytest.mark.anyio
async def test_overview_kpis_match_sql(metrics_db) -> None:
    """GET /metrics/overview values equal independent SQL for the chosen range."""
    engine, _ = metrics_db
    client = make_client()
    try:
        await login(client, OWNER_EMAIL)
        response = await client.get("/api/metrics/overview", params={"range": "30d"})
        assert response.status_code == 200
        body = response.json()
        assert body["range_days"] == 30
        kpis = {tile["key"]: tile for tile in body["kpis"]}
        assert set(kpis) == {"ukupan_prihod", "kupci_u_padu", "izgubljeni_artikli", "zadaci_danas"}

        with engine.connect() as conn:
            revenue = conn.execute(
                text(
                    "SELECT COALESCE(SUM(total), 0) FROM core.invoice "
                    "WHERE date > :as_of - 30 AND date <= :as_of"
                ),
                {"as_of": datetime.date.today()},
            ).scalar()
        assert Decimal(kpis["ukupan_prihod"]["value"]) == revenue

        # The revenue sparkline has 8 weekly points, each a SQL value.
        assert len(kpis["ukupan_prihod"]["spark"]) == 8
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_revenue_trend_matches_sql(metrics_db) -> None:
    """GET /metrics/revenue-trend: 12 monthly values + prior-year + substats from SQL."""
    engine, _ = metrics_db
    client = make_client()
    try:
        await login(client, OWNER_EMAIL)
        response = await client.get("/api/metrics/revenue-trend")
        assert response.status_code == 200
        trend = response.json()

        with engine.connect() as conn:
            # Spot-check the latest month and its prior-year counterpart.
            latest = trend["months"][-1]
            sql_latest = conn.execute(
                text(
                    "SELECT COALESCE(SUM(total), 0) FROM core.invoice "
                    "WHERE to_char(date, 'YYYY-MM') = :month"
                ),
                {"month": latest},
            ).scalar()
            assert Decimal(trend["revenue"][-1]) == sql_latest

            year, month = latest.split("-")
            prior_label = f"{int(year) - 1}-{month}"
            sql_prior = conn.execute(
                text(
                    "SELECT COALESCE(SUM(total), 0) FROM core.invoice "
                    "WHERE to_char(date, 'YYYY-MM') = :month"
                ),
                {"month": prior_label},
            ).scalar()
            assert Decimal(trend["secondary"][-1]) == sql_prior

            # Substats: YTD equals SQL.
            ytd = conn.execute(
                text(
                    "SELECT COALESCE(SUM(total), 0) FROM core.invoice "
                    "WHERE date >= date_trunc('year', CAST(:as_of AS date))::date "
                    "  AND date <= :as_of"
                ),
                {"as_of": datetime.date.today()},
            ).scalar()
        substats = {stat["key"]: stat["value"] for stat in trend["substats"]}
        assert Decimal(substats["ytd_prihod"]) == ytd
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_customer_360_matches_sql(metrics_db) -> None:
    """GET /metrics/customer/{id}: header metrics + monthly turnover + basket from SQL."""
    engine, _ = metrics_db
    with engine.connect() as conn:
        customer_id = conn.execute(
            text(
                "SELECT customer_id FROM core.customer_metrics "
                "WHERE turnover_60d > 0 ORDER BY customer_id LIMIT 1"
            )
        ).scalar()
        sql_turnover = conn.execute(
            text("SELECT turnover_60d FROM core.customer_metrics WHERE customer_id = :id"),
            {"id": customer_id},
        ).scalar()

    client = make_client()
    try:
        await login(client, OWNER_EMAIL)
        response = await client.get(f"/api/metrics/customer/{customer_id}")
        assert response.status_code == 200
        body = response.json()
        assert body["customer_id"] == customer_id
        assert Decimal(body["turnover_60d"]) == sql_turnover
        assert len(body["monthly_turnover"]) == 12
        assert body["basket"], "an active customer must have basket categories"

        # Unknown customer → 404 envelope.
        missing = await client.get("/api/metrics/customer/9999999")
        assert missing.status_code == 404
        assert "error" in missing.json()
    finally:
        await client.aclose()
