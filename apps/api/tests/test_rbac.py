"""M8 acceptance: RBAC — the D2 role matrix, enforced end-to-end through the API.

owner/admin: everything (admin additionally /settings/users + /ingest).
finance:     dashboard/metrics/reports/customers/articles — NO tasks/approvals.
sales_rep:   own tasks/customers/signals/articles only — NO dashboard/metrics/
             reports/approvals/settings.
unauthenticated: 401 everywhere except /health and /auth/login.
"""

import datetime

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tests.conftest import login, make_client
from valeri_api.scanner.scan import run_scan
from valeri_api.seed.users import ADMIN_EMAIL, FINANCE_EMAIL, OWNER_EMAIL

# Endpoints that carry finance-level data (rep must get 403).
FINANCE_ENDPOINTS = [
    "/api/dashboard",
    "/api/metrics/overview",
    "/api/metrics/revenue-trend",
    "/api/reports/owner/weekly",
    "/api/reports/owner/summary",
]

# Endpoints reps and finance must not touch at all.
OWNER_ADMIN_ONLY = ["/api/approvals"]
ADMIN_ONLY = ["/api/settings/users"]


def _reset_app_tables(session: Session) -> None:
    session.execute(
        text(
            "TRUNCATE audit.ai_log, audit.task_log, app.task_feedback, app.approval, "
            "app.owner_report, app.task, app.signal, app.learned_rule RESTART IDENTITY CASCADE"
        )
    )


@pytest.fixture(scope="module")
def rbac_db(db_engine: Engine, seed_data):
    """Seed + signals + tasks, so row-level scoping has data to scope."""
    from valeri_api.seed.loader import load, reset

    as_of = datetime.date.fromisoformat(seed_data.manifest["as_of"])
    with Session(db_engine) as session:
        _reset_app_tables(session)
        reset(session)
        load(seed_data, session)
        run_scan(session, as_of=as_of, create_tasks=True)
        session.commit()

    rep_user = next(user for user in seed_data.app_users if user["role"] == "sales_rep")

    yield db_engine, rep_user

    with Session(db_engine) as session:
        _reset_app_tables(session)
        reset(session)
        load(seed_data, session)
        session.commit()


# ── the milestone acceptance: a rep can't load finance data ──────────────────


@pytest.mark.anyio
async def test_rep_cannot_load_finance_data(rbac_db) -> None:
    """A sales_rep login gets 403 on every finance/owner surface."""
    _, rep_user = rbac_db
    client = make_client()
    try:
        await login(client, rep_user["email"])
        for endpoint in FINANCE_ENDPOINTS + OWNER_ADMIN_ONLY + ADMIN_ONLY:
            response = await client.get(endpoint)
            assert response.status_code == 403, f"rep should get 403 on {endpoint}"
            assert response.json()["error"]["code"] == "forbidden"
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_rep_sees_only_own(rbac_db) -> None:
    """Rep-scoped lists return only rows for the rep's currently assigned customers."""
    engine, rep_user = rbac_db

    # Ground truth from SQL: the rep's current customers.
    with engine.connect() as conn:
        own_customers = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT customer_id FROM ("
                    "  SELECT DISTINCT ON (customer_id) customer_id, sales_rep_id"
                    "  FROM core.customer_rep ORDER BY customer_id, from_date DESC"
                    ") cur WHERE sales_rep_id = :rep_id"
                ),
                {"rep_id": rep_user["sales_rep_id"]},
            )
        }
    assert own_customers, "the seeded rep must have assigned customers"

    client = make_client()
    try:
        await login(client, rep_user["email"])

        # Tasks: every returned task is assigned to this rep.
        tasks = await client.get("/api/tasks", params={"limit": 200})
        assert tasks.status_code == 200
        task_items = tasks.json()["items"]
        assert task_items, "the rep should see their own tasks"
        assert all(item["assignee_id"] == rep_user["sales_rep_id"] for item in task_items)

        # Customers: only own.
        customers = await client.get("/api/customers", params={"limit": 200})
        assert customers.status_code == 200
        customer_ids = {item["id"] for item in customers.json()["items"]}
        assert customer_ids, "the rep should see their own customers"
        assert customer_ids <= own_customers

        # At-risk customers: only own.
        at_risk = await client.get("/api/customers/at-risk")
        assert at_risk.status_code == 200
        assert {item["customer_id"] for item in at_risk.json()["items"]} <= own_customers

        # Signals: only own customers' signals.
        signals = await client.get("/api/signals", params={"limit": 200})
        assert signals.status_code == 200
        signal_customers = {
            item["customer_id"]
            for item in signals.json()["items"]
            if item["customer_id"] is not None
        }
        assert signal_customers <= own_customers

        # Lost articles: only own customers'.
        lost = await client.get("/api/articles/lost")
        assert lost.status_code == 200
        assert {item["customer_id"] for item in lost.json()["items"]} <= own_customers
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_owner_sees_everything_rep_sees_subset(rbac_db) -> None:
    """The owner's task/customer lists are supersets of the rep's."""
    _, rep_user = rbac_db
    owner = make_client()
    rep = make_client()
    try:
        await login(owner, OWNER_EMAIL)
        await login(rep, rep_user["email"])

        owner_tasks = await owner.get("/api/tasks", params={"limit": 200})
        rep_tasks = await rep.get("/api/tasks", params={"limit": 200})
        owner_ids = {item["id"] for item in owner_tasks.json()["items"]}
        rep_ids = {item["id"] for item in rep_tasks.json()["items"]}
        assert rep_ids <= owner_ids
        assert owner_ids - rep_ids, "the owner should also see other reps' tasks"

        owner_customers = await owner.get("/api/customers", params={"limit": 200})
        rep_customers = await rep.get("/api/customers", params={"limit": 200})
        assert {c["id"] for c in rep_customers.json()["items"]} < {
            c["id"] for c in owner_customers.json()["items"]
        }
    finally:
        await owner.aclose()
        await rep.aclose()


# ── finance + admin gating ────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_finance_and_admin_gating(rbac_db) -> None:
    """Finance can read dashboards/reports but not tasks/approvals; admin-only endpoints hold."""
    _, rep_user = rbac_db

    finance = make_client()
    owner = make_client()
    admin = make_client()
    try:
        await login(finance, FINANCE_EMAIL)
        await login(owner, OWNER_EMAIL)
        await login(admin, ADMIN_EMAIL)

        # Finance CAN load the finance surfaces.
        for endpoint in ["/api/dashboard", "/api/metrics/overview", "/api/customers"]:
            response = await finance.get(endpoint)
            assert response.status_code == 200, f"finance should access {endpoint}"

        # Finance CANNOT touch rep work queues or approvals or admin areas.
        for endpoint in ["/api/tasks", "/api/approvals", "/api/settings/users"]:
            response = await finance.get(endpoint)
            assert response.status_code == 403, f"finance should get 403 on {endpoint}"

        # /settings/users is admin-only: even the owner gets 403.
        owner_users = await owner.get("/api/settings/users")
        assert owner_users.status_code == 403
        admin_users = await admin.get("/api/settings/users")
        assert admin_users.status_code == 200

        # /settings/rule-config: owner + admin read; finance/rep cannot.
        assert (await owner.get("/api/settings/rule-config")).status_code == 200
        assert (await admin.get("/api/settings/rule-config")).status_code == 200
        assert (await finance.get("/api/settings/rule-config")).status_code == 403

        # Ingest is admin-only.
        assert (await owner.get("/api/ingest/report/1")).status_code in (403,)
        admin_ingest = await admin.get("/api/ingest/report/999999")
        assert admin_ingest.status_code == 404  # admin passes RBAC; report doesn't exist
    finally:
        await finance.aclose()
        await owner.aclose()
        await admin.aclose()


@pytest.mark.anyio
async def test_unauthenticated_gets_401(rbac_db) -> None:
    """Every protected endpoint requires a session; /health and /auth/login stay public."""
    client = make_client()
    try:
        protected = FINANCE_ENDPOINTS + [
            "/api/tasks",
            "/api/customers",
            "/api/customers/at-risk",
            "/api/articles",
            "/api/articles/lost",
            "/api/signals",
            "/api/approvals",
            "/api/settings/rule-config",
            "/api/settings/users",
            "/api/auth/me",
        ]
        for endpoint in protected:
            response = await client.get(endpoint)
            assert response.status_code == 401, f"{endpoint} should require auth"
            assert "error" in response.json()

        # Public endpoints.
        health = await client.get("/api/health")
        assert health.status_code == 200
    finally:
        await client.aclose()
