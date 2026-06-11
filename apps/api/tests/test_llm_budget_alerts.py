"""P3 budget alert: month spend ≥ alert_pct% of budget → llm_budget alert.

The alert flows through the existing ops derive_alerts → the owner's inbox bell.
The 'default' budget row governs when no month-specific row exists.
"""

import datetime

import httpx
import pytest
from sqlalchemy import Engine, text

from valeri_api.db import session_scope
from valeri_api.ops.runs import derive_alerts

pytestmark = pytest.mark.anyio


def _set_month_spend(engine: Engine, cost: str) -> None:
    today = datetime.date.today().isoformat()
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM audit.ai_log WHERE feature = 'budget_test'"))
        conn.execute(
            text(
                "INSERT INTO audit.ai_log (model, masked_input, feature, cost_usd, created_at) "
                "VALUES ('claude-haiku-4-5', '{}'::jsonb, 'budget_test', :cost, :day)"
            ),
            {"cost": cost, "day": today},
        )
        conn.commit()


def _clear(engine: Engine) -> None:
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM audit.ai_log WHERE feature = 'budget_test'"))
        conn.commit()


async def test_no_alert_below_threshold(seeded_db: Engine) -> None:
    """Default budget 50 USD, alert at 80% → 39 USD (78%) raises no alert."""
    _set_month_spend(seeded_db, "39.00")
    try:
        with session_scope() as session:
            kinds = {a["kind"] for a in derive_alerts(session)}
        assert "llm_budget" not in kinds
    finally:
        _clear(seeded_db)


async def test_alert_at_80_pct(seeded_db: Engine) -> None:
    """41 USD of a 50 USD budget = 82% → the llm_budget alert fires."""
    _set_month_spend(seeded_db, "41.00")
    try:
        with session_scope() as session:
            alerts = derive_alerts(session)
        budget_alerts = [a for a in alerts if a["kind"] == "llm_budget"]
        assert len(budget_alerts) == 1
        assert "82%" in budget_alerts[0]["message"]
    finally:
        _clear(seeded_db)


async def test_alert_surfaces_in_owner_bell(
    owner_client: httpx.AsyncClient, seeded_db: Engine
) -> None:
    _set_month_spend(seeded_db, "45.00")  # 90%
    try:
        body = (await owner_client.get("/api/inbox/summary")).json()
        assert body["alerts"] >= 1
        status = (await owner_client.get("/api/admin/ops/status")).json()
        assert any(a["kind"] == "llm_budget" for a in status["alerts"])
    finally:
        _clear(seeded_db)


async def test_default_period_fallback(seeded_db: Engine) -> None:
    """With no month-specific budget row, the 'default' row governs the alert."""
    period = datetime.date.today().strftime("%Y-%m")
    with seeded_db.connect() as conn:
        conn.execute(text("DELETE FROM app.llm_budget WHERE period = :p"), {"p": period})
        conn.commit()
    _set_month_spend(seeded_db, "48.00")  # 96% of the default 50
    try:
        with session_scope() as session:
            kinds = {a["kind"] for a in derive_alerts(session)}
        assert "llm_budget" in kinds
    finally:
        _clear(seeded_db)
