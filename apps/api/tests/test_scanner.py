"""M4 acceptance: the scanner over the seed detects every planted case and honors the guards.

- every planted decline / lost article / sleeping / narrow-basket case fires;
- the seasonal cafés do NOT fire;
- the code-swapped articles are NOT flagged as lost;
- a hand-inserted suppression learned_rule hides exactly the right future signal;
- re-scanning never duplicates open signals;
- every signal carries evidence + confidence + band + register.
"""

import datetime
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from valeri_api.scanner.scan import run_scan


def _reset_app_tables(session: Session) -> None:
    session.execute(text("TRUNCATE app.signal, app.learned_rule RESTART IDENTITY CASCADE"))


def _restore_seed(engine: Engine, seed_data) -> None:
    from valeri_api.seed.loader import load, reset

    with Session(engine) as session:
        _reset_app_tables(session)
        reset(session)
        load(seed_data, session)
        session.commit()


@pytest.fixture(scope="module")
def scanned_db(db_engine: Engine, seed_data):
    """Seed loaded + metrics recomputed + one full scan. Yields (engine, as_of, manifest)."""
    from valeri_api.seed.loader import load, reset

    as_of = datetime.date.fromisoformat(seed_data.manifest["as_of"])
    with Session(db_engine) as session:
        _reset_app_tables(session)
        reset(session)
        load(seed_data, session)
        run_scan(
            session, as_of=as_of, create_tasks=False
        )  # detection only (M5 tests the full flow)
        session.commit()

    yield db_engine, as_of, seed_data.manifest

    _restore_seed(db_engine, seed_data)


def _signals(engine: Engine, rule: str) -> list:
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT customer_id, article_id, evidence, confidence, conf_band, register, status "
                "FROM app.signal WHERE rule = :rule"
            ),
            {"rule": rule},
        ).all()


# ── planted cases fire ────────────────────────────────────────────────────────


def test_planted_declines_fire(scanned_db) -> None:
    engine, _, manifest = scanned_db
    decline_customers = {row.customer_id for row in _signals(engine, "customer_decline")}
    for case in manifest["declines"]:
        assert (
            case["customer_id"] in decline_customers
        ), f"planted decline {case['customer_id']} did not fire"


def test_seasonal_cafes_do_not_fire(scanned_db) -> None:
    """The seasonal guard: cafés with the same pattern last year are NOT declines."""
    engine, _, manifest = scanned_db
    decline_customers = {row.customer_id for row in _signals(engine, "customer_decline")}
    for case in manifest["seasonal_cafes"]:
        assert (
            case["customer_id"] not in decline_customers
        ), f"seasonal café {case['customer_id']} wrongly flagged as decline"


def test_planted_lost_articles_fire(scanned_db) -> None:
    engine, _, manifest = scanned_db
    lost_pairs = {(row.customer_id, row.article_id) for row in _signals(engine, "lost_article")}
    for case in manifest["lost_articles"]:
        assert (
            case["customer_id"],
            case["article_id"],
        ) in lost_pairs, (
            f"planted lost article {case['customer_id']}/{case['article_id']} did not fire"
        )


def test_code_swapped_articles_not_flagged(scanned_db) -> None:
    """The code-swap guard: retired codes never appear as lost articles."""
    engine, _, manifest = scanned_db
    lost_article_ids = {row.article_id for row in _signals(engine, "lost_article")}
    for case in manifest["code_swaps"]:
        assert (
            case["old_article_id"] not in lost_article_ids
        ), f"code-swapped article {case['old_code']} wrongly flagged as lost"


def test_planted_sleeping_customers_fire(scanned_db) -> None:
    engine, _, manifest = scanned_db
    sleeping_customers = {row.customer_id for row in _signals(engine, "sleeping_customer")}
    for case in manifest["sleeping"]:
        assert (
            case["customer_id"] in sleeping_customers
        ), f"planted sleeping customer {case['customer_id']} did not fire"


def test_planted_narrow_baskets_fire(scanned_db) -> None:
    engine, _, manifest = scanned_db
    narrow_customers = {row.customer_id for row in _signals(engine, "narrow_basket")}
    for case in manifest["narrow_baskets"]:
        assert (
            case["customer_id"] in narrow_customers
        ), f"planted narrow basket {case['customer_id']} did not fire"


# ── signal discipline ─────────────────────────────────────────────────────────


def test_every_signal_carries_evidence_confidence_register(scanned_db) -> None:
    """Principles 2, 3, 9: evidence + confidence (band) + register on every signal."""
    engine, as_of, _ = scanned_db
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT rule, evidence, confidence, conf_band, register, status FROM app.signal")
        ).all()

    assert rows, "the scan produced no signals at all"
    for row in rows:
        assert row.evidence, f"{row.rule}: empty evidence"
        assert "period" in row.evidence, f"{row.rule}: evidence missing period"
        assert "metric" in row.evidence, f"{row.rule}: evidence missing metric"
        assert Decimal("0") < row.confidence <= Decimal("1"), f"{row.rule}: bad confidence"
        assert row.conf_band in ("niska", "srednja", "visoka")
        expected_register = "preporuka" if row.rule == "narrow_basket" else "analiza"
        assert row.register == expected_register
        assert row.status == "new"


def test_rescan_does_not_duplicate(scanned_db, seed_data) -> None:
    """Running the scan again creates zero new signals (dedup on open signals)."""
    engine, as_of, _ = scanned_db
    with engine.connect() as conn:
        before = conn.execute(text("SELECT COUNT(*) FROM app.signal")).scalar()

    with Session(engine) as session:
        result = run_scan(session, as_of=as_of, recompute=False, create_tasks=False)
        session.commit()

    with engine.connect() as conn:
        after = conn.execute(text("SELECT COUNT(*) FROM app.signal")).scalar()

    assert result.total_inserted == 0
    assert after == before


def test_scheduler_has_daily_and_weekly_jobs() -> None:
    """The worker runs the daily scan, weekly cycle, M11 audit and M13 investigation poll."""
    from valeri_api.scanner.scheduler import create_scheduler

    scheduler = create_scheduler()
    job_ids = {job.id for job in scheduler.get_jobs()}
    assert job_ids == {
        "daily_scan",
        "weekly_scan",
        "over_suppression_audit",
        "investigation_poll",
    }


# ── learned-rule suppression (the M4 hook; learned rules are written in M10) ──


def test_hand_inserted_learned_rule_suppresses_the_right_signal(db_engine, seed_data) -> None:
    """An active suppression learned_rule hides exactly its target's future signal."""
    from valeri_api.seed.loader import load, reset

    as_of = datetime.date.fromisoformat(seed_data.manifest["as_of"])
    declines = seed_data.manifest["declines"]
    suppressed_customer = declines[0]["customer_id"]
    other_decline_customers = [case["customer_id"] for case in declines[1:]]

    with Session(db_engine) as session:
        _reset_app_tables(session)
        reset(session)
        load(seed_data, session)

        # Hand-insert the suppression (what M10's self-config loop will write).
        session.execute(
            text(
                "INSERT INTO app.learned_rule "
                "(domain, rule_type, scope, description, status, autonomy) VALUES "
                "('sales', 'suppress', CAST(:scope AS jsonb), "
                " 'Test: ignoriši pad prometa za ovog kupca', 'active', 'confirmed')"
            ),
            {
                "scope": (
                    '{"kind": "entity", "entity_type": "customer", '
                    f'"entity_id": {suppressed_customer}, "rule": "customer_decline"}}'
                )
            },
        )

        result = run_scan(session, as_of=as_of, create_tasks=False)
        session.commit()

    try:
        # M10: the suppressed detection is PERSISTED with status='suppressed'
        # (evidence kept for the auditor) — never as an open (new/tasked) signal.
        open_decline_customers = {
            row.customer_id
            for row in _signals(db_engine, "customer_decline")
            if row.status in ("new", "tasked")
        }
        assert (
            suppressed_customer not in open_decline_customers
        ), "suppression did not hide the signal"
        # … while the other planted declines still fire …
        for customer_id in other_decline_customers:
            assert customer_id in open_decline_customers, "suppression hid the wrong signal"
        # … and the scan counted + recorded the suppression (signal + hit).
        assert result.total_suppressed >= 1
        with db_engine.connect() as conn:
            suppressed_row = conn.execute(
                text(
                    "SELECT id FROM app.signal WHERE rule = 'customer_decline' "
                    "AND customer_id = :cid AND status = 'suppressed'"
                ),
                {"cid": suppressed_customer},
            ).scalar()
            assert suppressed_row is not None, "suppressed signal must be persisted (M10)"
            hit_count = conn.execute(
                text("SELECT COUNT(*) FROM app.suppression_hit WHERE signal_id = :sid"),
                {"sid": suppressed_row},
            ).scalar()
            assert hit_count >= 1, "every suppression writes a suppression_hit (M10)"

        # An expired suppression must NOT hide anything: expire it and rescan.
        with Session(db_engine) as session:
            session.execute(
                text("UPDATE app.learned_rule SET expires_at = now() - interval '1 day'")
            )
            rescan = run_scan(session, as_of=as_of, recompute=False, create_tasks=False)
            session.commit()
        open_after_expiry = {
            row.customer_id
            for row in _signals(db_engine, "customer_decline")
            if row.status in ("new", "tasked")
        }
        assert suppressed_customer in open_after_expiry, "expired suppression still active"
        assert rescan.total_inserted >= 1
        # M11: expiry is a visible lifecycle transition, not a silent filter.
        with db_engine.connect() as conn:
            expired_status = conn.execute(
                text("SELECT status FROM app.learned_rule ORDER BY id LIMIT 1")
            ).scalar()
        assert expired_status == "expired"
    finally:
        _restore_seed(db_engine, seed_data)
