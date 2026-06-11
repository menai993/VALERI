"""P3 admin LLM cost API: usage == SQL, recent, budget/pricing PATCH + decision + RBAC.

Dashboard aggregates must equal direct SQL over audit.ai_log; budget/pricing edits
write reversible threshold_change decisions; reads are owner/admin, writes admin.
"""

import datetime

import httpx
import pytest
from sqlalchemy import Engine, text

pytestmark = pytest.mark.anyio


def _seed_ai_log(engine: Engine) -> None:
    """A handful of priced ai_log rows this month, across features/models/users."""
    today = datetime.date.today().isoformat()
    rows = [
        ("claude-haiku-4-5", "tier1", "narration", 1, 1000, 500, "0.003500"),
        ("claude-haiku-4-5", "tier1", "intent", 1, 200, 50, "0.000450"),
        ("claude-sonnet-4-6", "tier2", "investigation", 2, 2000, 1000, "0.021000"),
        ("claude-opus-4-8", "tier2_strong", "investigation", 2, 1000, 1000, "0.030000"),
    ]
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM audit.ai_log WHERE feature IS NOT NULL"))
        for model, tier, feature, uid, inp, out, cost in rows:
            conn.execute(
                text(
                    "INSERT INTO audit.ai_log "
                    "(model, masked_input, output, tier, feature, user_id, "
                    " input_tokens, output_tokens, cost_usd, created_at) "
                    "VALUES (:m, '{}'::jsonb, '{}'::jsonb, :tier, :f, :uid, "
                    " :inp, :out, :cost, :day)"
                ),
                {
                    "m": model,
                    "tier": tier,
                    "f": feature,
                    "uid": uid,
                    "inp": inp,
                    "out": out,
                    "cost": cost,
                    "day": today,
                },
            )
        conn.commit()


async def test_usage_groups_match_sql(owner_client: httpx.AsyncClient, db_engine: Engine) -> None:
    _seed_ai_log(db_engine)
    try:
        body = (
            await owner_client.get("/api/admin/llm/usage", params={"group_by": "feature"})
        ).json()
        # Total spend == SQL sum.
        with db_engine.connect() as conn:
            total = conn.execute(
                text(
                    "SELECT sum(cost_usd) FROM audit.ai_log "
                    "WHERE to_char(created_at,'YYYY-MM') = to_char(now(),'YYYY-MM')"
                )
            ).scalar_one()
        assert float(body["total"]["cost_usd"]) == float(total)
        # investigation is the most expensive feature group (0.021 + 0.030).
        groups = {g["key"]: float(g["cost_usd"]) for g in body["groups"]}
        assert round(groups["investigation"], 6) == 0.051
        assert round(groups["narration"], 6) == 0.0035
    finally:
        with db_engine.connect() as conn:
            conn.execute(text("DELETE FROM audit.ai_log WHERE feature IS NOT NULL"))
            conn.commit()


async def test_usage_group_by_user_and_model(
    owner_client: httpx.AsyncClient, db_engine: Engine
) -> None:
    _seed_ai_log(db_engine)
    try:
        by_user = (
            await owner_client.get("/api/admin/llm/usage", params={"group_by": "user"})
        ).json()
        users = {g["key"]: float(g["cost_usd"]) for g in by_user["groups"]}
        assert round(users["2"], 6) == 0.051  # both investigations
        by_model = (
            await owner_client.get("/api/admin/llm/usage", params={"group_by": "model"})
        ).json()
        models = {g["key"] for g in by_model["groups"]}
        assert {"claude-haiku-4-5", "claude-sonnet-4-6", "claude-opus-4-8"} <= models
    finally:
        with db_engine.connect() as conn:
            conn.execute(text("DELETE FROM audit.ai_log WHERE feature IS NOT NULL"))
            conn.commit()


async def test_cost_per_useful_task_matches_sql(
    owner_client: httpx.AsyncClient, db_engine: Engine
) -> None:
    """Spend ÷ distinct tasks marked done (task_log outcome) in the range."""
    today = datetime.date.today().isoformat()
    _seed_ai_log(db_engine)
    task_ids: list[int] = []
    with db_engine.connect() as conn:
        conn.execute(text("DELETE FROM audit.task_log WHERE event = 'outcome'"))
        # Two distinct tasks acted on → cost-per-useful = total / 2.
        for _ in range(2):
            tid = conn.execute(
                text(
                    "INSERT INTO app.task (title, status, register) "
                    "VALUES ('cput test', 'done', 'preporuka') RETURNING id"
                )
            ).scalar_one()
            task_ids.append(tid)
            conn.execute(
                text(
                    "INSERT INTO audit.task_log (task_id, event, payload, at) "
                    "VALUES (:tid, 'outcome', '{\"status\":\"done\"}'::jsonb, :day)"
                ),
                {"tid": tid, "day": today},
            )
        conn.commit()
    try:
        body = (await owner_client.get("/api/admin/llm/usage")).json()
        cput = body["cost_per_useful_task"]
        assert cput["useful_tasks"] == 2
        assert round(cput["value"], 6) == round(float(cput["cost_usd"]) / 2, 6)
    finally:
        with db_engine.connect() as conn:
            conn.execute(text("DELETE FROM audit.ai_log WHERE feature IS NOT NULL"))
            conn.execute(
                text("DELETE FROM audit.task_log WHERE task_id = ANY(:ids)"),
                {"ids": task_ids},
            )
            conn.execute(text("DELETE FROM app.task WHERE id = ANY(:ids)"), {"ids": task_ids})
            conn.commit()


async def test_recent_orders_by_cost(owner_client: httpx.AsyncClient, db_engine: Engine) -> None:
    _seed_ai_log(db_engine)
    try:
        body = (await owner_client.get("/api/admin/llm/recent", params={"limit": 3})).json()
        costs = [float(r["cost_usd"]) for r in body["items"]]
        assert costs == sorted(costs, reverse=True)
        assert round(costs[0], 6) == 0.030000  # the opus investigation
    finally:
        with db_engine.connect() as conn:
            conn.execute(text("DELETE FROM audit.ai_log WHERE feature IS NOT NULL"))
            conn.commit()


async def test_budget_patch_writes_decision(
    admin_client: httpx.AsyncClient, db_engine: Engine
) -> None:
    with db_engine.connect() as conn:
        before = conn.execute(
            text("SELECT count(*) FROM app.decision WHERE kind = 'threshold_change'")
        ).scalar_one()
    resp = await admin_client.patch(
        "/api/admin/llm/budget", json={"limit_usd": "120.00", "alert_pct": 75}
    )
    assert resp.status_code == 200
    assert float(resp.json()["limit_usd"]) == 120.0
    with db_engine.connect() as conn:
        after = conn.execute(
            text("SELECT count(*) FROM app.decision WHERE kind = 'threshold_change'")
        ).scalar_one()
        latest = conn.execute(
            text(
                "SELECT payload FROM app.decision WHERE kind = 'threshold_change' "
                "ORDER BY id DESC LIMIT 1"
            )
        ).scalar_one()
        # restore the default seed for other tests
        conn.execute(
            text(
                "UPDATE app.llm_budget SET limit_usd = 50, alert_pct = 80 WHERE period = 'default'"
            )
        )
        conn.commit()
    assert after == before + 1
    assert latest["new"]["limit_usd"] == "120.00"


async def test_pricing_patch_writes_decision(
    admin_client: httpx.AsyncClient, db_engine: Engine
) -> None:
    resp = await admin_client.patch(
        "/api/admin/llm/pricing",
        json={
            "model": "claude-haiku-4-5",
            "input_per_mtok": "1.50",
            "output_per_mtok": "6.00",
            "cache_read_per_mtok": "0.15",
            "batch_discount": "0.5",
        },
    )
    assert resp.status_code == 200
    with db_engine.connect() as conn:
        latest = conn.execute(
            text(
                "SELECT payload FROM app.decision WHERE kind = 'threshold_change' "
                "ORDER BY id DESC LIMIT 1"
            )
        ).scalar_one()
        # restore the seed price
        conn.execute(
            text(
                "UPDATE app.llm_pricing SET input_per_mtok = 1.00, output_per_mtok = 5.00, "
                "cache_read_per_mtok = 0.10 WHERE model = 'claude-haiku-4-5'"
            )
        )
        conn.commit()
    assert latest["model"] == "claude-haiku-4-5"
    assert latest["new"]["input_per_mtok"] == "1.50"


async def test_rbac_rep_and_finance_blocked(
    rep_client: httpx.AsyncClient, finance_client: httpx.AsyncClient
) -> None:
    assert (await rep_client.get("/api/admin/llm/usage")).status_code == 403
    assert (await finance_client.get("/api/admin/llm/usage")).status_code == 403
    assert (
        await rep_client.patch("/api/admin/llm/budget", json={"limit_usd": "1.00"})
    ).status_code == 403


async def test_owner_reads_but_cannot_write(owner_client: httpx.AsyncClient) -> None:
    assert (await owner_client.get("/api/admin/llm/budget")).status_code == 200
    # owner is not admin → cannot patch
    assert (
        await owner_client.patch("/api/admin/llm/budget", json={"limit_usd": "1.00"})
    ).status_code == 403
