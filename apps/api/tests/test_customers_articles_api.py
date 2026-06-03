"""M8 acceptance: customers + articles endpoints — lists, details, at-risk, lost articles."""

import datetime

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tests.conftest import login, make_client
from valeri_api.scanner.scan import run_scan
from valeri_api.seed.users import OWNER_EMAIL


@pytest.fixture(scope="module")
def api_db(db_engine: Engine, seed_data):
    """Seed + signals + tasks for the list/detail endpoints."""
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
async def test_customers_list_search_pagination(api_db, seed_data) -> None:
    """GET /customers: pagination, name search, segment filter, 404 detail envelope."""
    engine, _ = api_db
    client = make_client()
    try:
        await login(client, OWNER_EMAIL)

        # Pagination walks every customer exactly once.
        seen: set[int] = set()
        cursor = None
        while True:
            params = {"limit": 30}
            if cursor is not None:
                params["cursor"] = cursor
            page = await client.get("/api/customers", params=params)
            assert page.status_code == 200
            body = page.json()
            page_ids = {item["id"] for item in body["items"]}
            assert not (seen & page_ids), "pagination must not repeat rows"
            seen |= page_ids
            cursor = body["next_cursor"]
            if cursor is None:
                break
        assert len(seen) == len(seed_data.customers)

        # Name search.
        sample_name = seed_data.customers[0]["name"]
        search = await client.get("/api/customers", params={"query": sample_name[:6]})
        assert search.status_code == 200
        assert any(item["name"] == sample_name for item in search.json()["items"])

        # Segment filter.
        segment = await client.get("/api/customers", params={"segment": "hotel", "limit": 200})
        assert all(item["segment"] == "hotel" for item in segment.json()["items"])

        # Detail: customer + contacts + metrics + signals/tasks.
        detail = await client.get(f"/api/customers/{seed_data.customers[0]['id']}")
        assert detail.status_code == 200
        body = detail.json()
        assert body["customer"]["name"] == sample_name
        assert "contacts" in body and "metrics" in body

        # 404 envelope.
        missing = await client.get("/api/customers/9999999")
        assert missing.status_code == 404
        assert "error" in missing.json()
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_at_risk_rows_are_decline_signals(api_db, seed_data) -> None:
    """GET /customers/at-risk: rows mirror open decline signals with risk bands."""
    engine, _ = api_db
    client = make_client()
    try:
        await login(client, OWNER_EMAIL)
        response = await client.get("/api/customers/at-risk")
        assert response.status_code == 200
        items = response.json()["items"]
        assert items, "planted declines must appear as at-risk rows"

        planted_declines = {case["customer_id"] for case in seed_data.manifest["declines"]}
        returned = {item["customer_id"] for item in items}
        assert planted_declines <= returned, "every planted decline must be in the at-risk table"

        for item in items:
            assert item["risk_band"] in ("nizak", "srednji", "visok")
            assert item["evidence"]["metric"] == "turnover_60d"
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_articles_and_lost_articles(api_db, seed_data) -> None:
    """GET /articles + /articles/lost: catalog and the lost-article signals with evidence."""
    engine, _ = api_db
    client = make_client()
    try:
        await login(client, OWNER_EMAIL)

        # Catalog list + search.
        articles = await client.get("/api/articles", params={"limit": 10})
        assert articles.status_code == 200
        assert len(articles.json()["items"]) == 10

        # Lost articles: every planted lost article appears with evidence.
        lost = await client.get("/api/articles/lost")
        assert lost.status_code == 200
        items = lost.json()["items"]
        planted = seed_data.manifest["lost_articles"]
        planted_pairs = {(case["customer_id"], case["article_id"]) for case in planted}
        returned_pairs = {(item["customer_id"], item["article_id"]) for item in items}
        assert planted_pairs <= returned_pairs

        for item in items:
            assert item["article_code"]
            assert item["gap_days"] > 0
            assert item["evidence"]
            assert item["register"] in ("analiza", "preporuka", "akcija")

        # Filter by customer.
        first_customer = items[0]["customer_id"]
        filtered = await client.get("/api/articles/lost", params={"customer_id": first_customer})
        assert all(item["customer_id"] == first_customer for item in filtered.json()["items"])

        # Article detail + 404.
        detail = await client.get(f"/api/articles/{items[0]['article_id']}")
        assert detail.status_code == 200
        missing = await client.get("/api/articles/9999999")
        assert missing.status_code == 404
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_signals_list_and_feedback(api_db) -> None:
    """GET /signals + POST /signals/{id}/feedback (recorded on the signal's task)."""
    engine, _ = api_db
    client = make_client()
    try:
        await login(client, OWNER_EMAIL)

        signals = await client.get("/api/signals", params={"rule": "customer_decline"})
        assert signals.status_code == 200
        items = signals.json()["items"]
        assert items
        assert all(item["rule"] == "customer_decline" for item in items)

        # Detail carries the envelope.
        detail = await client.get(f"/api/signals/{items[0]['id']}")
        assert detail.status_code == 200
        assert detail.json()["evidence"]
        assert detail.json()["conf_band"] in ("niska", "srednja", "visoka")

        # Feedback lands on the signal's task + in the task log.
        feedback = await client.post(
            f"/api/signals/{items[0]['id']}/feedback",
            json={"useful": False, "reason": "Kupac je sezonski"},
        )
        assert feedback.status_code == 201
        task_id = feedback.json()["task_id"]

        with engine.connect() as conn:
            stored = conn.execute(
                text("SELECT useful, reason FROM app.task_feedback WHERE task_id = :id"),
                {"id": task_id},
            ).first()
            logged = conn.execute(
                text(
                    "SELECT COUNT(*) FROM audit.task_log "
                    "WHERE task_id = :id AND event = 'feedback'"
                ),
                {"id": task_id},
            ).scalar()
        assert stored is not None and stored.useful is False
        assert logged >= 1
    finally:
        await client.aclose()
