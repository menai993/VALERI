"""M8 acceptance: the dashboard — every rendered number equals an independent SQL value.

GET /dashboard assembles KPIs, the revenue trend, AI insights, at-risk and
lost-article tables and the owner-report summary. Principle 1: all of it is SQL
pass-through; principle 2/3/9: every AI row carries evidence + confidence + register.
"""

import datetime
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tests.conftest import login, make_client
from tests.fakes import AutoFakeLLMClient
from valeri_api.seed.users import OWNER_EMAIL


def _reset_app_tables(session: Session) -> None:
    session.execute(
        text(
            "TRUNCATE audit.ai_log, audit.task_log, app.task_feedback, app.approval, "
            "app.owner_report, app.task, app.signal, app.learned_rule RESTART IDENTITY CASCADE"
        )
    )


@pytest.fixture(scope="module")
def dashboard_db(db_engine: Engine, seed_data):
    """Seed → scan → tasks → weekly report: the full data the dashboard reads."""
    from valeri_api.scanner.scheduler import run_weekly_cycle
    from valeri_api.seed.loader import load, reset

    as_of = datetime.date.fromisoformat(seed_data.manifest["as_of"])
    with Session(db_engine) as session:
        _reset_app_tables(session)
        reset(session)
        load(seed_data, session)
        run_weekly_cycle(session, as_of=as_of, client=AutoFakeLLMClient())
        session.commit()

    yield db_engine, as_of

    with Session(db_engine) as session:
        _reset_app_tables(session)
        reset(session)
        load(seed_data, session)
        session.commit()


@pytest.fixture
async def dashboard_payload(dashboard_db):
    """The /dashboard response (fetched once per test that needs it)."""
    client = make_client()
    try:
        await login(client, OWNER_EMAIL)
        response = await client.get("/api/dashboard")
        assert response.status_code == 200, response.text
        yield dashboard_db[0], response.json()
    finally:
        await client.aclose()


# ── numbers == SQL ────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_dashboard_numbers_match_sql(dashboard_payload) -> None:
    """Every KPI/trend/table number equals an independent SQL computation."""
    engine, body = dashboard_payload
    today = datetime.date.today()

    with engine.connect() as conn:
        # KPI: ukupan prihod (default range 30d) vs prior 30d.
        revenue_30d = conn.execute(
            text(
                "SELECT COALESCE(SUM(total), 0) FROM core.invoice "
                "WHERE date > :as_of - 30 AND date <= :as_of"
            ),
            {"as_of": today},
        ).scalar()
        prior_30d = conn.execute(
            text(
                "SELECT COALESCE(SUM(total), 0) FROM core.invoice "
                "WHERE date > :as_of - 60 AND date <= :as_of - 30"
            ),
            {"as_of": today},
        ).scalar()

        # KPI: open detection counts.
        declining_customers = conn.execute(
            text(
                "SELECT COUNT(DISTINCT customer_id) FROM app.signal "
                "WHERE rule = 'customer_decline' AND status IN ('new', 'tasked')"
            )
        ).scalar()
        lost_articles_open = conn.execute(
            text(
                "SELECT COUNT(*) FROM app.signal "
                "WHERE rule = 'lost_article' AND status IN ('new', 'tasked')"
            )
        ).scalar()

        # KPI: tasks.
        open_tasks = conn.execute(
            text("SELECT COUNT(*) FROM app.task WHERE status = 'open'")
        ).scalar()
        due_tasks = conn.execute(
            text("SELECT COUNT(*) FROM app.task WHERE status = 'open' AND due_date <= :as_of"),
            {"as_of": today},
        ).scalar()

    kpis = {tile["key"]: tile for tile in body["kpis"]}
    assert Decimal(kpis["ukupan_prihod"]["value"]) == revenue_30d
    assert Decimal(kpis["ukupan_prihod"]["prior_value"]) == prior_30d
    assert kpis["kupci_u_padu"]["value"] == declining_customers
    assert kpis["izgubljeni_artikli"]["value"] == lost_articles_open
    assert kpis["zadaci_danas"]["value"] == due_tasks
    assert kpis["zadaci_danas"]["progress"]["total"] >= open_tasks

    # Revenue trend: each month equals SQL.
    trend = body["revenue_trend"]
    assert len(trend["months"]) == 12
    assert len(trend["revenue"]) == 12
    assert len(trend["secondary"]) == 12
    with engine.connect() as conn:
        for month_label, revenue_value in zip(trend["months"], trend["revenue"], strict=True):
            sql_value = conn.execute(
                text(
                    "SELECT COALESCE(SUM(total), 0) FROM core.invoice "
                    "WHERE to_char(date, 'YYYY-MM') = :month"
                ),
                {"month": month_label},
            ).scalar()
            assert Decimal(revenue_value) == sql_value, f"month {month_label} mismatch"

    # At-risk rows: values equal the signals' SQL-computed evidence.
    with engine.connect() as conn:
        for row in body["customers_at_risk"]:
            signal = conn.execute(
                text("SELECT evidence, confidence FROM app.signal WHERE id = :id"),
                {"id": row["signal_id"]},
            ).one()
            assert Decimal(row["value"]) == Decimal(str(signal.evidence["value"]))
            assert Decimal(row["baseline"]) == Decimal(str(signal.evidence["baseline"]))
            assert Decimal(row["confidence"]) == signal.confidence

    # Lost-article rows: from lost_article signals only.
    with engine.connect() as conn:
        for row in body["lost_articles"]:
            rule = conn.execute(
                text("SELECT rule FROM app.signal WHERE id = :id"), {"id": row["signal_id"]}
            ).scalar()
            assert rule == "lost_article"


@pytest.mark.anyio
async def test_dashboard_envelope_on_every_ai_row(dashboard_payload) -> None:
    """Every AI-derived row carries register + confidence + conf_band + evidence."""
    _, body = dashboard_payload

    ai_rows = body["ai_insights"] + body["customers_at_risk"] + body["lost_articles"]
    assert ai_rows, "the planted cases must produce AI rows"
    for row in ai_rows:
        assert row["register"] in ("analiza", "preporuka", "akcija")
        assert row["conf_band"] in ("niska", "srednja", "visoka")
        assert Decimal(row["confidence"]) >= 0
        assert row["evidence"], "every AI row must carry its SQL evidence"

    # At-risk rows additionally carry a risk band.
    for row in body["customers_at_risk"]:
        assert row["risk_band"] in ("nizak", "srednji", "visok")

    # The owner-report summary is present (the weekly cycle ran) and register-tagged.
    summary = body["owner_report_summary"]
    assert summary is not None
    for metric in summary["metrics"]:
        assert metric["register"] in ("analiza", "preporuka", "akcija")
    for bullet in summary["bullets"]:
        assert bullet["register"] in ("analiza", "preporuka", "akcija")

    # Phase-2 placeholders are explicit, never fake data.
    assert body["rep_activity"] is None  # rep activity is still C-CRM2
    # M11: no learned rules in this fixture → the suppressed list is honestly empty.
    assert body["recently_suppressed"] == []


@pytest.mark.anyio
async def test_dashboard_opportunities_block(dashboard_payload) -> None:
    """C-CRM1: the Prilike block replaces the placeholder + every number equals SQL."""
    engine, body = dashboard_payload
    opportunities = body["opportunities"]
    assert opportunities is not None, "the seed plants opportunities → block is not null"

    from decimal import Decimal

    with engine.connect() as conn:
        defaults = conn.execute(
            text("SELECT value FROM app.rule_config WHERE rule='crm' AND param='stage_probability'")
        ).scalar()
        defaults = {stage: Decimal(str(p)) for stage, p in defaults.items()}
        open_rows = conn.execute(
            text(
                "SELECT value, probability, stage FROM app.opportunity "
                "WHERE stage IN ('lead','qualified','proposal','negotiation') AND value IS NOT NULL"
            )
        ).all()
        won = conn.execute(text("SELECT COUNT(*) FROM app.opportunity WHERE stage='won'")).scalar()
        closed = conn.execute(
            text("SELECT COUNT(*) FROM app.opportunity WHERE stage IN ('won','lost')")
        ).scalar()
        open_count = conn.execute(
            text(
                "SELECT COUNT(*) FROM app.opportunity "
                "WHERE stage IN ('lead','qualified','proposal','negotiation')"
            )
        ).scalar()

    weighted = sum(
        (r.value * (r.probability if r.probability is not None else defaults[r.stage])).quantize(
            Decimal("0.01")
        )
        for r in open_rows
    ).quantize(Decimal("0.01"))

    assert opportunities["open_count"] == open_count
    assert Decimal(opportunities["weighted_value"]) == weighted
    expected_conv = (
        (Decimal(won) / Decimal(closed)).quantize(Decimal("0.0001"))
        if closed
        else Decimal("0.0000")
    )
    assert Decimal(opportunities["conversion_rate"]).quantize(Decimal("0.0001")) == expected_conv
    # Top deals are sorted by weighted value (the strongest first).
    assert len(opportunities["top"]) <= 5


@pytest.mark.anyio
async def test_dashboard_range_presets(dashboard_db) -> None:
    """?range=90d changes the KPI window; the value matches SQL for that window."""
    engine, _ = dashboard_db
    client = make_client()
    try:
        await login(client, OWNER_EMAIL)
        response = await client.get("/api/dashboard", params={"range": "90d"})
        assert response.status_code == 200
        kpis = {tile["key"]: tile for tile in response.json()["kpis"]}

        with engine.connect() as conn:
            revenue_90d = conn.execute(
                text(
                    "SELECT COALESCE(SUM(total), 0) FROM core.invoice "
                    "WHERE date > :as_of - 90 AND date <= :as_of"
                ),
                {"as_of": datetime.date.today()},
            ).scalar()
        assert Decimal(kpis["ukupan_prihod"]["value"]) == revenue_90d
    finally:
        await client.aclose()


# ── M11: the recently-suppressed list ─────────────────────────────────────────


def test_recently_suppressed_rows_match_sql(dashboard_db) -> None:
    """The dashboard's recently-suppressed payload is pure SQL pass-through."""
    import json

    from valeri_api.metrics.dashboard import recently_suppressed_rows

    engine, _ = dashboard_db
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    try:
        customer = session.execute(text("SELECT id, name FROM core.customer LIMIT 1")).one()
        rule_id = session.execute(
            text(
                "INSERT INTO app.learned_rule "
                "(domain, rule_type, scope, description, status, autonomy) VALUES "
                "('sales', 'suppress', CAST(:scope AS jsonb), "
                " 'Test pravilo za dashboard', 'active', 'confirmed') RETURNING id"
            ),
            {
                "scope": json.dumps(
                    {
                        "kind": "entity",
                        "entity_type": "customer",
                        "entity_id": customer.id,
                        "rule": "customer_decline",
                    }
                )
            },
        ).scalar()
        signal_id = session.execute(
            text(
                "INSERT INTO app.signal "
                "(rule, customer_id, evidence, confidence, conf_band, register, status) VALUES "
                "('customer_decline', :cid, "
                ' CAST(\'{"metric": "turnover_60d", "ratio": "0.5"}\' AS jsonb), '
                " 0.8, 'visoka', 'analiza', 'suppressed') RETURNING id"
            ),
            {"cid": customer.id},
        ).scalar()
        hit_ids = [
            session.execute(
                text(
                    "INSERT INTO app.suppression_hit (learned_rule_id, signal_id) "
                    "VALUES (:rid, :sid) RETURNING id"
                ),
                {"rid": rule_id, "sid": signal_id},
            ).scalar()
            for _ in range(2)
        ]

        rows = recently_suppressed_rows(session)
        assert len(rows) == 2
        # Newest first; every field is the SQL value, rehydrated name included.
        assert [row.hit_id for row in rows] == sorted(hit_ids, reverse=True)
        assert rows[0].learned_rule_id == rule_id
        assert rows[0].rule == "customer_decline"
        assert rows[0].customer_id == customer.id
        assert rows[0].customer_name == customer.name
        assert rows[0].description == "Test pravilo za dashboard"
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()
