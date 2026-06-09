"""C-CRM2 acceptance: rep activity logging + rollups (TDD — before the implementation).

1. Per-rep activity rollups (counts by kind + completion) equal independent SQL.
2. Logging is RBAC-gated: reps log their own; owner/admin any; finance read-only.
3. A rep's view is scoped to their own row.

No LLM in activity logging — pure CRUD + SQL COUNT.
"""

import datetime

import pytest
from sqlalchemy import Engine, text

from tests.conftest import login, make_client
from valeri_api.seed.users import ADMIN_EMAIL, FINANCE_EMAIL, OWNER_EMAIL


def _today_iso() -> str:
    return datetime.date.today().isoformat()


# ── 1/2. rollups == SQL ───────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_activity_rollup_matches_sql(seeded_db: Engine) -> None:
    """Per-rep totals + by-kind counts + completion equal an independent SQL count."""
    client = make_client()
    try:
        await login(client, OWNER_EMAIL)
        body = (await client.get("/api/reps/activity", params={"date": _today_iso()})).json()
        assert body["reps"], "the seed plants activities → at least one rep row"

        with seeded_db.connect() as conn:
            for rep in body["reps"]:
                sql = conn.execute(
                    text(
                        "SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE done) AS done "
                        "FROM app.activity "
                        "WHERE sales_rep_id = :rep "
                        "AND date_trunc('month', at) = date_trunc('month', CAST(:as_of AS date))"
                    ),
                    {"rep": rep["sales_rep_id"], "as_of": _today_iso()},
                ).one()
                assert rep["total"] == sql.total
                assert rep["done"] == sql.done
                # by_kind sums to total.
                assert sum(rep["by_kind"].values()) == rep["total"]
                # completion = done / total.
                expected = f"{sql.done / sql.total:.4f}" if sql.total else "0.0000"
                assert rep["completion"] == expected
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_by_kind_matches_sql(seeded_db: Engine) -> None:
    client = make_client()
    try:
        await login(client, ADMIN_EMAIL)
        body = (await client.get("/api/reps/activity", params={"date": _today_iso()})).json()
        with seeded_db.connect() as conn:
            for rep in body["reps"]:
                for kind, count in rep["by_kind"].items():
                    sql_count = conn.execute(
                        text(
                            "SELECT COUNT(*) FROM app.activity WHERE sales_rep_id = :rep "
                            "AND kind = :kind AND date_trunc('month', at) = "
                            "date_trunc('month', CAST(:as_of AS date))"
                        ),
                        {"rep": rep["sales_rep_id"], "kind": kind, "as_of": _today_iso()},
                    ).scalar()
                    assert count == sql_count, f"rep {rep['sales_rep_id']} kind {kind}"
    finally:
        await client.aclose()


# ── 3. logging RBAC ───────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_log_activity_rep_scoped(seeded_db: Engine, seed_data) -> None:
    """A rep's POST forces sales_rep_id to theirs; owner may set any; finance → 403."""
    rep_user = next(u for u in seed_data.app_users if u["role"] == "sales_rep")
    rep_client = make_client()
    owner_client = make_client()
    finance_client = make_client()
    try:
        await login(rep_client, rep_user["email"])
        await login(owner_client, OWNER_EMAIL)
        await login(finance_client, FINANCE_EMAIL)

        # Rep: sales_rep_id forced to theirs even if they try to spoof another.
        other_rep_id = rep_user["sales_rep_id"] + 1
        created = await rep_client.post(
            "/api/activity", json={"kind": "call", "sales_rep_id": other_rep_id}
        )
        assert created.status_code == 201, created.text
        assert created.json()["sales_rep_id"] == rep_user["sales_rep_id"]
        rep_activity_id = created.json()["id"]

        # Owner: may log for a named rep.
        owner_logged = await owner_client.post(
            "/api/activity", json={"kind": "meeting", "sales_rep_id": rep_user["sales_rep_id"]}
        )
        assert owner_logged.status_code == 201
        owner_activity_id = owner_logged.json()["id"]

        # Finance: forbidden.
        finance_logged = await finance_client.post("/api/activity", json={"kind": "call"})
        assert finance_logged.status_code == 403

        # Invalid kind → 422.
        bad = await rep_client.post("/api/activity", json={"kind": "teleportation"})
        assert bad.status_code == 422

        with seeded_db.connect() as conn:
            conn.execute(
                text("DELETE FROM app.activity WHERE id = ANY(:ids)"),
                {"ids": [rep_activity_id, owner_activity_id]},
            )
            conn.commit()
    finally:
        await rep_client.aclose()
        await owner_client.aclose()
        await finance_client.aclose()


@pytest.mark.anyio
async def test_rep_activity_view_scoped(seeded_db: Engine, seed_data) -> None:
    """A rep's GET /reps/activity returns only their own row; owner sees all."""
    rep_user = next(u for u in seed_data.app_users if u["role"] == "sales_rep")
    rep_client = make_client()
    owner_client = make_client()
    try:
        await login(rep_client, rep_user["email"])
        await login(owner_client, OWNER_EMAIL)

        rep_body = (
            await rep_client.get("/api/reps/activity", params={"date": _today_iso()})
        ).json()
        rep_ids = {r["sales_rep_id"] for r in rep_body["reps"]}
        assert rep_ids <= {rep_user["sales_rep_id"]}  # only their own (or empty)

        owner_body = (
            await owner_client.get("/api/reps/activity", params={"date": _today_iso()})
        ).json()
        assert len(owner_body["reps"]) >= len(rep_body["reps"])
    finally:
        await rep_client.aclose()
        await owner_client.aclose()


@pytest.mark.anyio
async def test_activity_invalid_date(seeded_db: Engine) -> None:
    client = make_client()
    try:
        await login(client, OWNER_EMAIL)
        bad = await client.get("/api/reps/activity", params={"date": "not-a-date"})
        assert bad.status_code == 422
    finally:
        await client.aclose()
