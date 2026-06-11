"""P3 spend guards: per-feature daily caps + the near-cap throttle.

The investigation cap refuses a run with a clear 429; the throttle defers only
non-essential roles (scheduled narration/drafts/auditor) — chat is spared.
"""

import datetime

import httpx
import pytest
from sqlalchemy import Engine, text

from valeri_api.llm.spend_guard import (
    feature_cap_reached,
    is_non_essential,
    non_essential_throttled,
)

anyio = pytest.mark.anyio


def _seed_investigations(engine: Engine, n: int) -> None:
    """N investigation RUNS today (the investigation cap counts runs, not calls)."""
    with engine.connect() as conn:
        for _ in range(n):
            conn.execute(
                text(
                    "INSERT INTO app.investigation (trigger, question, status) "
                    "VALUES ('user', 'cap test', 'queued')"
                )
            )
        conn.commit()


def test_feature_cap_reached(db_session) -> None:
    """investigation cap is 10/day (seed), counted as RUNS: 9 → free, 10 → capped."""
    for _ in range(9):
        db_session.execute(
            text(
                "INSERT INTO app.investigation (trigger, question, status) "
                "VALUES ('user', 'cap test', 'queued')"
            )
        )
    db_session.flush()
    assert feature_cap_reached(db_session, "investigation") is False
    db_session.execute(
        text(
            "INSERT INTO app.investigation (trigger, question, status) "
            "VALUES ('user', 'cap test', 'queued')"
        )
    )
    db_session.flush()
    assert feature_cap_reached(db_session, "investigation") is True


def test_no_cap_for_uncapped_feature(db_session) -> None:
    assert feature_cap_reached(db_session, "narration") is False


def test_non_essential_classification(db_session) -> None:
    assert is_non_essential(db_session, "report_narration") is True
    assert is_non_essential(db_session, "simple_qa") is False  # chat is never deferrable


def test_throttle_tracks_budget(seeded_db: Engine) -> None:
    """throttle_pct is 90 (seed); 46/50 USD = 92% → throttled, chat still spared."""
    today = datetime.date.today().isoformat()
    with seeded_db.connect() as conn:
        conn.execute(text("DELETE FROM audit.ai_log WHERE feature = 'throttle_test'"))
        conn.execute(
            text(
                "INSERT INTO audit.ai_log (model, masked_input, feature, cost_usd, created_at) "
                "VALUES ('m', '{}'::jsonb, 'throttle_test', 46.00, :day)"
            ),
            {"day": today},
        )
        conn.commit()
    try:
        from valeri_api.db import session_scope

        with session_scope() as session:
            assert non_essential_throttled(session) is True
            # chat role is not non-essential → the chokepoint won't defer it
            assert is_non_essential(session, "simple_qa") is False
    finally:
        with seeded_db.connect() as conn:
            conn.execute(text("DELETE FROM audit.ai_log WHERE feature = 'throttle_test'"))
            conn.commit()


@anyio
async def test_daily_cap_blocks_investigation(
    owner_client: httpx.AsyncClient, db_engine: Engine
) -> None:
    """At the cap, POST /investigations returns 429 feature_capped and creates no run."""
    _seed_investigations(db_engine, 10)
    try:
        with db_engine.connect() as conn:
            before = conn.execute(text("SELECT count(*) FROM app.investigation")).scalar_one()
        resp = await owner_client.post("/api/investigations", json={"question": "zašto pad?"})
        assert resp.status_code == 429
        assert resp.json()["error"]["code"] == "feature_capped"
        with db_engine.connect() as conn:
            after = conn.execute(text("SELECT count(*) FROM app.investigation")).scalar_one()
        assert after == before  # no run queued
    finally:
        with db_engine.connect() as conn:
            conn.execute(text("DELETE FROM app.investigation WHERE question = 'cap test'"))
            conn.commit()
