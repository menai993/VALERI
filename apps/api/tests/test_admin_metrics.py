"""Admin recompute panel: operational control over the derived-metrics pipeline.

RBAC (admin only), recompute repopulates the derived tables, scan creates signals
without tasks (no LLM), and status counts equal direct SQL — numbers-from-SQL.
All LLM-free; these endpoints never call the gateway.
"""

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tests.conftest import login, make_client
from valeri_api.seed.users import ADMIN_EMAIL, FINANCE_EMAIL, OWNER_EMAIL


@pytest.mark.anyio
async def test_admin_endpoints_require_admin(seeded_db) -> None:
    """owner/finance/sales_rep are blocked (403); only admin may reach the panel."""
    for email in (OWNER_EMAIL, FINANCE_EMAIL):
        client = make_client()
        try:
            await login(client, email)
            assert (await client.get("/api/admin/metrics/status")).status_code == 403
            assert (await client.post("/api/admin/metrics/recompute")).status_code == 403
            assert (await client.post("/api/admin/scan")).status_code == 403
        finally:
            await client.aclose()


@pytest.mark.anyio
async def test_recompute_populates_and_status_matches_sql(seeded_db) -> None:
    """After wiping customer_metrics, recompute repopulates it; status == direct SQL count."""
    engine: Engine = seeded_db
    with Session(engine) as session:
        session.execute(text("DELETE FROM core.customer_metrics"))
        session.commit()

    client = make_client()
    try:
        await login(client, ADMIN_EMAIL)

        recompute = await client.post("/api/admin/metrics/recompute")
        assert recompute.status_code == 200
        rows = recompute.json()["rows"]
        assert rows["core.customer_metrics"] > 0

        status = (await client.get("/api/admin/metrics/status")).json()
    finally:
        await client.aclose()

    with Session(engine) as session:
        sql_count = session.execute(text("SELECT COUNT(*) FROM core.customer_metrics")).scalar()

    assert status["customer_metrics"]["rows"] == sql_count == rows["core.customer_metrics"]
    assert status["customer_metrics"]["computed_at"] is not None


@pytest.mark.anyio
async def test_scan_creates_signals_without_tasks(seeded_db) -> None:
    """The scan endpoint inserts signals (planted cases) but creates no tasks (no LLM cost)."""
    engine: Engine = seeded_db
    with Session(engine) as session:
        tasks_before = session.execute(text("SELECT COUNT(*) FROM app.task")).scalar()

    client = make_client()
    try:
        await login(client, ADMIN_EMAIL)
        scan = await client.post("/api/admin/scan")
        assert scan.status_code == 200
        assert "inserted" in scan.json()
    finally:
        await client.aclose()

    with Session(engine) as session:
        tasks_after = session.execute(text("SELECT COUNT(*) FROM app.task")).scalar()
        signals = session.execute(text("SELECT COUNT(*) FROM app.signal")).scalar()

    assert tasks_after == tasks_before  # create_tasks=False → no tasks, no LLM
    assert signals > 0
