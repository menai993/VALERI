"""M7 acceptance: the weekly owner report (TDD — written before the implementation).

1. Every stored number equals an independent SQL computation (principle 1).
2. All 7 sections present and register-tagged (D5); placeholder + akcija statuses.
3. Narrative numbers pass the number contract; invented numbers → template fallback.
4. The report is an idempotent stored snapshot; different weeks coexist.
5. No raw PII in report-narration prompts or audit.ai_log.
6. The summary block is extracted from the stored payload (no recomputation).
7. The API serves the weekly report + summary with proper 404 envelopes.

All LLM interaction uses fakes — no gateway needed.
"""

import datetime
import json
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tests.fakes import AutoFakeLLMClient, ScriptedFakeLLMClient

SECTION_KEYS = [
    "kpi_pregled",
    "najveci_padovi",
    "izgubljeni_artikli",
    "uspavani_kupci",
    "zadaci_sedmice",
    "nedavno_potisnuto",
    "prilike_po_izvoru",  # C-CRM2
    "prihod_vs_plan",  # C-CRM2
    "prijedlozi_poruka",
]

EXPECTED_REGISTERS = {
    "kpi_pregled": "analiza",
    "najveci_padovi": "analiza",
    "izgubljeni_artikli": "analiza",
    "uspavani_kupci": "analiza",
    "zadaci_sedmice": "preporuka",
    "nedavno_potisnuto": "analiza",
    "prilike_po_izvoru": "analiza",  # C-CRM2
    "prihod_vs_plan": "analiza",  # C-CRM2
    "prijedlozi_poruka": "akcija",
}


def _reset_app_tables(session: Session) -> None:
    session.execute(
        text(
            "TRUNCATE audit.ai_log, audit.task_log, app.task_feedback, app.approval, "
            "app.owner_report, app.task, app.signal, app.learned_rule RESTART IDENTITY CASCADE"
        )
    )


def _restore_seed(engine: Engine, seed_data) -> None:
    from valeri_api.seed.loader import load, reset

    with Session(engine) as session:
        _reset_app_tables(session)
        reset(session)
        load(seed_data, session)
        session.commit()


@pytest.fixture(scope="module")
def reported_db(db_engine: Engine, seed_data):
    """The full weekly cycle: seed → scan → tasks → report + drafts (fake LLM)."""
    from valeri_api.scanner.scheduler import run_weekly_cycle
    from valeri_api.seed.loader import load, reset

    as_of = datetime.date.fromisoformat(seed_data.manifest["as_of"])
    fake = AutoFakeLLMClient()
    with Session(db_engine) as session:
        _reset_app_tables(session)
        reset(session)
        load(seed_data, session)
        _, report = run_weekly_cycle(session, as_of=as_of, client=fake)
        session.commit()
        report_id = report.id
        week_start, week_end = report.week_start, report.week_end

    yield db_engine, report_id, week_start, week_end, fake, as_of

    _restore_seed(db_engine, seed_data)


def _payload(engine: Engine, report_id: int) -> dict:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT payload FROM app.owner_report WHERE id = :id"), {"id": report_id}
        ).scalar()


def _sections_by_key(payload: dict) -> dict:
    return {section["key"]: section for section in payload["sections"]}


# ── 1. aggregates match SQL ───────────────────────────────────────────────────


def test_report_aggregates_match_sql(reported_db) -> None:
    """Every number in the stored report equals an independent SQL computation."""
    engine, report_id, week_start, week_end, _, _ = reported_db
    payload = _payload(engine, report_id)
    sections = _sections_by_key(payload)
    kpi = sections["kpi_pregled"]["data"]

    with engine.connect() as conn:
        week_revenue = conn.execute(
            text("SELECT COALESCE(SUM(total), 0) FROM core.invoice WHERE date BETWEEN :a AND :b"),
            {"a": week_start, "b": week_end},
        ).scalar()
        prior_revenue = conn.execute(
            text("SELECT COALESCE(SUM(total), 0) FROM core.invoice WHERE date BETWEEN :a AND :b"),
            {
                "a": week_start - datetime.timedelta(days=7),
                "b": week_start - datetime.timedelta(days=1),
            },
        ).scalar()
        new_signals = conn.execute(
            text("SELECT COUNT(*) FROM app.signal WHERE created_at::date BETWEEN :a AND :b"),
            {"a": week_start, "b": week_end},
        ).scalar()
        new_tasks = conn.execute(
            text("SELECT COUNT(*) FROM app.task WHERE created_at::date BETWEEN :a AND :b"),
            {"a": week_start, "b": week_end},
        ).scalar()
        open_tasks = conn.execute(
            text("SELECT COUNT(*) FROM app.task WHERE status = 'open'")
        ).scalar()

    # To-the-cent equality (Decimals are stored as exact strings).
    assert Decimal(kpi["week_revenue"]) == week_revenue
    assert Decimal(kpi["prior_week_revenue"]) == prior_revenue
    assert kpi["new_signals"] == new_signals
    assert kpi["new_tasks"] == new_tasks
    assert kpi["open_tasks"] == open_tasks

    # Every decline row equals its signal's SQL-computed evidence + confidence.
    decline_items = sections["najveci_padovi"]["data"]["items"]
    assert decline_items, "the seed's planted declines must appear in the report"
    with engine.connect() as conn:
        for item in decline_items:
            row = conn.execute(
                text("SELECT evidence, confidence FROM app.signal WHERE id = :id"),
                {"id": item["signal_id"]},
            ).one()
            assert Decimal(item["value"]) == Decimal(str(row.evidence["value"]))
            assert Decimal(item["baseline"]) == Decimal(str(row.evidence["baseline"]))
            assert Decimal(item["delta_pct"]) == Decimal(str(row.evidence["delta_pct"]))
            assert Decimal(item["confidence"]) == row.confidence

    # Lost-article rows equal their signals' evidence.
    lost_items = sections["izgubljeni_artikli"]["data"]["items"]
    assert lost_items, "the seed's planted lost articles must appear in the report"
    with engine.connect() as conn:
        for item in lost_items:
            row = conn.execute(
                text("SELECT evidence FROM app.signal WHERE id = :id"),
                {"id": item["signal_id"]},
            ).one()
            assert item["article_code"] == row.evidence["article_code"]
            assert item["gap_days"] == int(str(row.evidence["gap_days"]))

    # Task stats equal SQL counts.
    stats = sections["zadaci_sedmice"]["data"]["stats"]
    with engine.connect() as conn:
        sql_stats = conn.execute(
            text(
                "SELECT COUNT(*) AS total, "
                "COUNT(*) FILTER (WHERE status = 'open') AS n_open, "
                "COUNT(*) FILTER (WHERE status = 'done') AS n_done "
                "FROM app.task WHERE created_at::date BETWEEN :a AND :b"
            ),
            {"a": week_start, "b": week_end},
        ).one()
    assert stats["total"] == sql_stats.total
    assert stats["open"] == sql_stats.n_open
    assert stats["done"] == sql_stats.n_done


# ── 2. register tags everywhere ───────────────────────────────────────────────


def test_report_sections_register_tagged(reported_db) -> None:
    """All 7 sections, each with its D5 register; honest empty states; drafts carry status."""
    engine, report_id, *_ = reported_db
    payload = _payload(engine, report_id)

    assert [section["key"] for section in payload["sections"]] == SECTION_KEYS

    for section in payload["sections"]:
        assert section["register"] == EXPECTED_REGISTERS[section["key"]], section["key"]
        assert section["title"]
        assert section["narrative"]
        assert section["narrative_source"] in ("llm", "template")

    # Section 6 (M11): no learned rules in this fixture → honest empty state, real shape.
    suppressed = _sections_by_key(payload)["nedavno_potisnuto"]
    assert suppressed["data"]["items"] == []
    assert suppressed["data"]["total_hits"] == 0
    assert suppressed["data"]["na_provjeri_count"] == 0
    assert "placeholder" not in suppressed["data"]  # the M7 placeholder is gone
    assert "Nema potisnutih signala" in suppressed["narrative"]

    # Section items: akcija register (on the section) + an approval status each.
    drafts = _sections_by_key(payload)["prijedlozi_poruka"]
    assert drafts["data"]["items"], "decline/sleeping tasks must produce message drafts"
    for item in drafts["data"]["items"]:
        assert item["status"] in ("draft", "pending_approval")
        assert item["message"]
        assert item["approval_id"]


# ── 2c. the C-CRM2 owner-report sections ──────────────────────────────────────


def test_opportunity_source_and_revenue_plan_sections(reported_db) -> None:
    """C-CRM2: the two new sections render register-tagged with numbers == SQL."""
    engine, report_id, *_ = reported_db
    payload = _payload(engine, report_id)
    sections = _sections_by_key(payload)

    # Opportunity-source attribution + avg value: counts/values equal SQL.
    opp = sections["prilike_po_izvoru"]
    assert opp["register"] == "analiza"
    assert opp["narrative"]
    with engine.connect() as conn:
        sql_sources = conn.execute(
            text(
                "SELECT COALESCE(source, 'nepoznato') AS source, COUNT(*) AS count "
                "FROM app.opportunity GROUP BY COALESCE(source, 'nepoznato')"
            )
        ).all()
        sql_avg = conn.execute(
            text(
                "SELECT COALESCE(AVG(value), 0)::numeric(14,2) FROM app.opportunity "
                "WHERE value IS NOT NULL"
            )
        ).scalar()
    api_counts = {row["source"]: row["count"] for row in opp["data"]["items"]}
    for row in sql_sources:
        assert api_counts.get(row.source) == row.count
    assert Decimal(opp["data"]["stats"]["avg_value"]) == sql_avg

    # Revenue-vs-plan + forecast: actual MTD equals SQL.
    plan = sections["prihod_vs_plan"]
    assert plan["register"] == "analiza"
    assert plan["narrative"]
    week_end = datetime.date.fromisoformat(payload["week_end"])
    with engine.connect() as conn:
        actual = conn.execute(
            text(
                "SELECT COALESCE(SUM(total), 0)::numeric(14,2) FROM core.invoice "
                "WHERE date_trunc('month', date) = date_trunc('month', CAST(:d AS date)) "
                "AND date <= CAST(:d AS date)"
            ),
            {"d": week_end},
        ).scalar()
    assert Decimal(plan["data"]["actual_mtd"]) == actual


# ── 2b. the recently-suppressed section (M11) ─────────────────────────────────


def test_recently_suppressed_section_filled(reported_db) -> None:
    """A week with suppression hits → the section lists them; every count equals SQL."""
    from valeri_api.reports.builder import build_weekly_report, extract_summary

    engine, _, _, _, _, as_of = reported_db
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    try:
        # Plant: an active learned rule + a suppressed signal + 3 hits in the NEXT week
        # (a different snapshot than the module fixture's report).
        next_week_day = as_of + datetime.timedelta(days=7)
        customer_id = session.execute(text("SELECT id FROM core.customer LIMIT 1")).scalar()
        rule_id = session.execute(
            text(
                "INSERT INTO app.learned_rule "
                "(domain, rule_type, scope, description, status, autonomy) VALUES "
                "('sales', 'suppress', CAST(:scope AS jsonb), "
                " 'Test pravilo: ne prijavljuj pad za ovog kupca', 'active', 'confirmed') "
                "RETURNING id"
            ),
            {
                "scope": json.dumps(
                    {
                        "kind": "entity",
                        "entity_type": "customer",
                        "entity_id": customer_id,
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
            {"cid": customer_id},
        ).scalar()
        for _ in range(3):
            session.execute(
                text(
                    "INSERT INTO app.suppression_hit (learned_rule_id, signal_id, suppressed_at) "
                    "VALUES (:rid, :sid, :at)"
                ),
                {"rid": rule_id, "sid": signal_id, "at": next_week_day},
            )

        report = build_weekly_report(session, week_end=next_week_day, client=AutoFakeLLMClient())
        suppressed = next(s for s in report.payload["sections"] if s["key"] == "nedavno_potisnuto")

        # Counts equal SQL (principle 1).
        sql_hits = session.execute(
            text(
                "SELECT COUNT(*) FROM app.suppression_hit "
                "WHERE suppressed_at >= :ws AND suppressed_at < CAST(:we AS date) + 1"
            ),
            {"ws": report.week_start, "we": report.week_end},
        ).scalar()
        assert suppressed["data"]["total_hits"] == sql_hits == 3
        assert len(suppressed["data"]["items"]) == 1
        item = suppressed["data"]["items"][0]
        assert item["learned_rule_id"] == rule_id
        assert item["hits"] == 3
        # The narrative carries the SQL counts (template — no LLM spent on counting).
        assert "3" in suppressed["narrative"]
        assert suppressed["narrative_source"] == "template"

        # The section now contributes a summary bullet (it is no longer a placeholder).
        summary = extract_summary(report)
        assert any("potisnuo" in bullet.text for bullet in summary.bullets)
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


# ── 3. narrative numbers come from SQL ────────────────────────────────────────


def test_report_narrative_numbers_from_sql(reported_db) -> None:
    """Narratives pass the number contract; invented numbers → template fallback."""
    from valeri_api.llm.masking import collect_allowed_numbers
    from valeri_api.llm.validators import check_number_contract
    from valeri_api.reports.builder import build_weekly_report

    engine, report_id, week_start, week_end, _, as_of = reported_db
    payload = _payload(engine, report_id)

    # a) With a rule-following client: every narrative's numbers exist in its
    #    section's SQL data (+ the week boundary dates).
    llm_narrated = [s for s in payload["sections"] if s["narrative_source"] == "llm"]
    assert llm_narrated, "data sections should have been LLM-narrated by the fake client"
    for section in payload["sections"]:
        allowed = collect_allowed_numbers(
            {"data": section["data"], "week": [payload["week_start"], payload["week_end"]]}
        )
        violations = check_number_contract(section["narrative"], allowed)
        assert violations == [], f"section {section['key']} invented numbers: {violations}"

    # b) A client that always invents numbers → every section falls back to the
    #    template (which renders only SQL values). Done in a rolled-back
    #    transaction so the module's stored report stays untouched.
    invented = json.dumps(
        {
            "text": "Promet je pao za tačno 98765.43 KM što je izuzetno zabrinjavajuće.",
            "register": "analiza",
        },
        ensure_ascii=False,
    )
    with Session(engine) as session:
        session.execute(text("DELETE FROM app.owner_report WHERE id = :id"), {"id": report_id})
        bad_fake = ScriptedFakeLLMClient([invented] * 100)
        rebuilt = build_weekly_report(session, week_end=as_of, client=bad_fake)
        session.flush()
        rebuilt_payload = json.loads(json.dumps(rebuilt.payload))
        session.rollback()  # the original snapshot survives

    assert bad_fake.captured, "the failing client must have been called"
    for section in rebuilt_payload["sections"]:
        assert (
            section["narrative_source"] == "template"
        ), f"section {section['key']} should have fallen back to the template"
        allowed = collect_allowed_numbers(
            {
                "data": section["data"],
                "week": [rebuilt_payload["week_start"], rebuilt_payload["week_end"]],
            }
        )
        assert check_number_contract(section["narrative"], allowed) == []
        assert "98765.43" not in section["narrative"], "invented numbers must never be stored"


# ── 4. stored snapshot semantics ──────────────────────────────────────────────


def test_report_is_stored_snapshot(reported_db) -> None:
    """Same week → idempotent (existing snapshot returned); other weeks coexist."""
    from valeri_api.reports.builder import build_weekly_report

    engine, report_id, week_start, week_end, _, as_of = reported_db

    with Session(engine) as session:
        # Same week: the existing snapshot returns, nothing new is created.
        again = build_weekly_report(session, week_end=as_of)
        assert again.id == report_id
        n_for_week = session.execute(
            text("SELECT COUNT(*) FROM app.owner_report WHERE week_start = :ws"),
            {"ws": week_start},
        ).scalar()
        assert n_for_week == 1

        # An earlier week coexists as its own snapshot.
        earlier = build_weekly_report(session, week_end=as_of - datetime.timedelta(days=7))
        session.commit()
        earlier_id = earlier.id
        assert earlier_id != report_id
        assert earlier.week_end == week_start - datetime.timedelta(days=1)

        total = session.execute(text("SELECT COUNT(*) FROM app.owner_report")).scalar()
        assert total == 2

    # Clean up the extra snapshot to keep module state predictable.
    with Session(engine) as session:
        session.execute(text("DELETE FROM app.owner_report WHERE id = :id"), {"id": earlier_id})
        session.commit()


# ── 5. no PII in prompts or ai_log ────────────────────────────────────────────


def test_report_no_pii_in_prompts(reported_db, seed_data) -> None:
    """Report prompts carry pseudonyms only; stored narratives are rehydrated."""
    engine, report_id, _, _, fake, _ = reported_db

    real_customer_names = {customer["name"] for customer in seed_data.customers}
    contact_pii = set()
    for contact in seed_data.contacts:
        contact_pii.add(contact["name"])
        contact_pii.add(contact["email"])
        contact_pii.add(contact["phone"])

    # a) No prompt contains any real customer name or contact PII; pseudonyms appear.
    assert fake.captured, "report narration should have sent prompts"
    all_prompts = "\n".join(item["system"] + "\n" + item["user"] for item in fake.captured)
    for name in real_customer_names:
        assert name not in all_prompts, f"customer name {name!r} leaked into a report prompt"
    for pii in contact_pii:
        assert pii not in all_prompts, f"contact PII {pii!r} leaked into a report prompt"
    assert "Kupac-" in all_prompts, "pseudonyms missing from report prompts"

    # b) audit.ai_log.masked_input is equally clean.
    with engine.connect() as conn:
        masked_inputs = [
            json.dumps(row[0], ensure_ascii=False)
            for row in conn.execute(text("SELECT masked_input FROM audit.ai_log"))
        ]
    assert masked_inputs
    for masked in masked_inputs:
        for name in real_customer_names:
            assert name not in masked, f"customer name {name!r} leaked into ai_log"
        for pii in contact_pii:
            assert pii not in masked, f"contact PII {pii!r} leaked into ai_log"

    # c) Stored narratives (human-facing) are rehydrated: real names, no pseudonyms.
    payload = _payload(engine, report_id)
    narratives = "\n".join(section["narrative"] for section in payload["sections"])
    assert "Kupac-" not in narratives, "pseudonyms must be rehydrated in the stored report"
    assert any(
        name in narratives for name in real_customer_names
    ), "rehydration should put real customer names into the stored narratives"


# ── 6. the summary block ──────────────────────────────────────────────────────


def test_summary_block(reported_db) -> None:
    """Summary metrics/bullets are pass-through extractions from the stored payload."""
    from valeri_api.reports.builder import extract_summary
    from valeri_api.reports.models import OwnerReport

    engine, report_id, week_start, week_end, _, _ = reported_db
    payload = _payload(engine, report_id)
    kpi = _sections_by_key(payload)["kpi_pregled"]["data"]

    with Session(engine) as session:
        report = session.get(OwnerReport, report_id)
        summary = extract_summary(report)

    assert summary.week_start == week_start
    assert summary.week_end == week_end

    # Metrics: values are pass-through from the stored KPI data (no recomputation).
    assert len(summary.metrics) == 4
    for metric in summary.metrics:
        assert metric.label
        assert metric.register in ("analiza", "preporuka", "akcija")
    metric_values = [metric.value for metric in summary.metrics]
    assert kpi["week_revenue"] in metric_values
    assert kpi["open_tasks"] in metric_values

    # Bullets: one per non-placeholder section, each carrying that section's register.
    non_placeholder = [s for s in payload["sections"] if not s["data"].get("placeholder")]
    assert len(summary.bullets) == len(non_placeholder)
    narratives = {section["narrative"]: section["register"] for section in non_placeholder}
    for bullet in summary.bullets:
        assert bullet.text in narratives
        assert bullet.register == narratives[bullet.text]


# ── 7. the API ────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_api_weekly_and_summary(reported_db) -> None:
    """GET weekly + summary serve the stored snapshot; 404 envelope when absent."""
    engine, report_id, week_start, week_end, _, _ = reported_db
    from tests.conftest import login
    from valeri_api.main import app
    from valeri_api.seed.users import OWNER_EMAIL

    payload = _payload(engine, report_id)
    stored_kpi = _sections_by_key(payload)["kpi_pregled"]["data"]

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, OWNER_EMAIL)  # M8: report API requires owner/admin/finance
        # The latest stored report.
        response = await client.get("/api/reports/owner/weekly")
        assert response.status_code == 200
        body = response.json()
        assert body["week_start"] == str(week_start)
        assert body["week_end"] == str(week_end)
        assert [section["key"] for section in body["sections"]] == SECTION_KEYS

        # Numbers in the response are the stored SQL values, passed through.
        api_kpi = next(s for s in body["sections"] if s["key"] == "kpi_pregled")["data"]
        assert api_kpi == stored_kpi
        for section in body["sections"]:
            assert section["register"] in ("analiza", "preporuka", "akcija")

        # Query by week_end (any date inside the week resolves to its report).
        response = await client.get(
            "/api/reports/owner/weekly", params={"week_end": str(week_start)}
        )
        assert response.status_code == 200
        assert response.json()["week_start"] == str(week_start)

        # The summary block.
        response = await client.get("/api/reports/owner/summary")
        assert response.status_code == 200
        summary = response.json()
        assert len(summary["metrics"]) == 4
        assert summary["bullets"]
        for metric in summary["metrics"]:
            assert metric["register"] in ("analiza", "preporuka", "akcija")
        for bullet in summary["bullets"]:
            assert bullet["register"] in ("analiza", "preporuka", "akcija")

        # 404 envelope for a week with no stored report.
        response = await client.get("/api/reports/owner/weekly", params={"week_end": "2020-01-05"})
        assert response.status_code == 404
        assert "error" in response.json()
