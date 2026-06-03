"""C-CRM1 acceptance: the opportunity pipeline (TDD — written before the implementation).

1. Pipeline math (weighted value, conversion) equals an independent SQL computation.
2. Effective probability = explicit probability OR the stage default (in rule_config).
3. Stage history is append-only (one row per transition).
4. Writes are RBAC-gated: reps → own customers only; finance read-only.
5. The dashboard 'Prilike' block matches SQL and replaces the placeholder.

No LLM in this track — pure CRUD + SQL aggregation against the seeded opportunities.
"""

from decimal import Decimal

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tests.conftest import login, make_client
from valeri_api.seed.users import ADMIN_EMAIL, FINANCE_EMAIL, OWNER_EMAIL

# ── helpers: the independent SQL truth ────────────────────────────────────────

OPEN_STAGES = ("lead", "qualified", "proposal", "negotiation")


def _stage_defaults(engine: Engine) -> dict[str, Decimal]:
    with engine.connect() as conn:
        value = conn.execute(
            text(
                "SELECT value FROM app.rule_config "
                "WHERE rule = 'crm' AND param = 'stage_probability'"
            )
        ).scalar()
    return {stage: Decimal(str(p)) for stage, p in value.items()}


def _sql_weighted_value(engine: Engine, stages: tuple[str, ...]) -> Decimal:
    """SUM(value × COALESCE(probability, stage_default)) over the given stages — pure SQL."""
    defaults = _stage_defaults(engine)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT value, probability, stage FROM app.opportunity "
                "WHERE stage = ANY(:stages) AND value IS NOT NULL"
            ),
            {"stages": list(stages)},
        ).all()
    total = Decimal("0")
    for row in rows:
        prob = row.probability if row.probability is not None else defaults[row.stage]
        total += (row.value * prob).quantize(Decimal("0.01"))
    return total.quantize(Decimal("0.01"))


def _sql_conversion(engine: Engine) -> Decimal:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT COUNT(*) FILTER (WHERE stage = 'won') AS won, "
                "COUNT(*) FILTER (WHERE stage IN ('won','lost')) AS closed FROM app.opportunity"
            )
        ).one()
    return (
        (Decimal(row.won) / Decimal(row.closed)).quantize(Decimal("0.0001"))
        if row.closed
        else Decimal("0.0000")
    )


# ── 1/2/4. pipeline math == SQL ───────────────────────────────────────────────


@pytest.mark.anyio
async def test_pipeline_weighted_value_matches_sql(seeded_db: Engine) -> None:
    """GET /pipeline total + per-stage weighted value equal independent SQL."""
    client = make_client()
    try:
        await login(client, OWNER_EMAIL)
        response = await client.get("/api/opportunities/pipeline")
        assert response.status_code == 200, response.text
        body = response.json()

        # The seed must have planted opportunities (the screen/tests need data).
        assert body["open_count"] >= 1

        # Total weighted value over open stages == SQL.
        assert Decimal(body["total_weighted_value"]) == _sql_weighted_value(seeded_db, OPEN_STAGES)

        # Each kanban column's weighted value == SQL for that stage.
        for column in body["stages"]:
            assert Decimal(column["weighted_value"]) == _sql_weighted_value(
                seeded_db, (column["stage"],)
            ), column["stage"]
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_conversion_rate_matches_sql(seeded_db: Engine) -> None:
    client = make_client()
    try:
        await login(client, OWNER_EMAIL)
        body = (await client.get("/api/opportunities/pipeline")).json()
        assert Decimal(body["conversion_rate"]).quantize(Decimal("0.0001")) == _sql_conversion(
            seeded_db
        )
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_effective_probability_uses_stage_default(seeded_db: Engine) -> None:
    """An opportunity with NULL probability contributes its stage default; explicit overrides."""
    client = make_client()
    try:
        await login(client, OWNER_EMAIL)
        defaults = _stage_defaults(seeded_db)
        items = (await client.get("/api/opportunities")).json()["items"]

        no_prob = next(o for o in items if o["probability"] is None and o["value"] is not None)
        expected_default = defaults[no_prob["stage"]]
        assert Decimal(no_prob["effective_probability"]) == expected_default
        assert Decimal(no_prob["weighted_value"]) == (
            Decimal(no_prob["value"]) * expected_default
        ).quantize(Decimal("0.01"))

        explicit = next(o for o in items if o["probability"] is not None and o["value"] is not None)
        assert Decimal(explicit["effective_probability"]) == Decimal(explicit["probability"])
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_stage_probability_lives_in_rule_config(seeded_db: Engine) -> None:
    """Changing crm.stage_probability changes the weighted value — nothing hard-coded."""
    client = make_client()
    try:
        await login(client, OWNER_EMAIL)
        before = Decimal(
            (await client.get("/api/opportunities/pipeline")).json()["total_weighted_value"]
        )

        # Halve every default; weighted value (for opps without explicit probability) drops.
        with Session(seeded_db) as session:
            current = session.execute(
                text(
                    "SELECT value FROM app.rule_config "
                    "WHERE rule='crm' AND param='stage_probability'"
                )
            ).scalar()
            halved = {stage: round(float(p) / 2, 4) for stage, p in current.items()}
            import json as _json

            session.execute(
                text(
                    "UPDATE app.rule_config SET value = CAST(:v AS jsonb) "
                    "WHERE rule='crm' AND param='stage_probability'"
                ),
                {"v": _json.dumps(halved)},
            )
            session.commit()

        after = Decimal(
            (await client.get("/api/opportunities/pipeline")).json()["total_weighted_value"]
        )
        assert after < before

        # Restore (other tests share the module-scoped seeded DB).
        with Session(seeded_db) as session:
            import json as _json

            session.execute(
                text(
                    "UPDATE app.rule_config SET value = CAST(:v AS jsonb) "
                    "WHERE rule='crm' AND param='stage_probability'"
                ),
                {"v": _json.dumps({stage: float(p) for stage, p in current.items()})},
            )
            session.commit()
    finally:
        await client.aclose()


# ── 3. CRUD + append-only stage history ───────────────────────────────────────


@pytest.mark.anyio
async def test_create_appends_initial_stage_history(seeded_db: Engine) -> None:
    client = make_client()
    try:
        await login(client, OWNER_EMAIL)
        with seeded_db.connect() as conn:
            customer_id = conn.execute(text("SELECT id FROM core.customer LIMIT 1")).scalar()

        created = await client.post(
            "/api/opportunities",
            json={
                "customer_id": customer_id,
                "title": "Nova testna prilika",
                "value": 5000,
                "stage": "qualified",
            },
        )
        assert created.status_code == 201, created.text
        opp_id = created.json()["id"]
        assert created.json()["customer_name"] is not None  # rehydrated for humans
        assert created.json()["stage"] == "qualified"

        with seeded_db.connect() as conn:
            history = conn.execute(
                text("SELECT stage FROM app.opportunity_stage_history WHERE opportunity_id = :id"),
                {"id": opp_id},
            ).all()
        assert [row.stage for row in history] == ["qualified"]

        # Cleanup.
        with Session(seeded_db) as session:
            session.execute(
                text("DELETE FROM app.opportunity_stage_history WHERE opportunity_id = :id"),
                {"id": opp_id},
            )
            session.execute(text("DELETE FROM app.opportunity WHERE id = :id"), {"id": opp_id})
            session.commit()
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_stage_change_appends_history(seeded_db: Engine) -> None:
    client = make_client()
    try:
        await login(client, ADMIN_EMAIL)
        with seeded_db.connect() as conn:
            customer_id = conn.execute(text("SELECT id FROM core.customer LIMIT 1")).scalar()
        opp_id = (
            await client.post(
                "/api/opportunities",
                json={
                    "customer_id": customer_id,
                    "title": "Prilika za prelazak faza",
                    "stage": "lead",
                },
            )
        ).json()["id"]

        # A stage change appends a history row.
        moved = await client.patch(f"/api/opportunities/{opp_id}", json={"stage": "proposal"})
        assert moved.status_code == 200
        assert moved.json()["stage"] == "proposal"

        # A non-stage change appends nothing.
        await client.patch(f"/api/opportunities/{opp_id}", json={"title": "Preimenovana prilika"})

        with seeded_db.connect() as conn:
            stages = [
                row.stage
                for row in conn.execute(
                    text(
                        "SELECT stage FROM app.opportunity_stage_history "
                        "WHERE opportunity_id = :id ORDER BY id"
                    ),
                    {"id": opp_id},
                )
            ]
        assert stages == ["lead", "proposal"]  # initial + the one transition, append-only

        with Session(seeded_db) as session:
            session.execute(
                text("DELETE FROM app.opportunity_stage_history WHERE opportunity_id = :id"),
                {"id": opp_id},
            )
            session.execute(text("DELETE FROM app.opportunity WHERE id = :id"), {"id": opp_id})
            session.commit()
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_api_envelopes(seeded_db: Engine) -> None:
    client = make_client()
    try:
        await login(client, OWNER_EMAIL)
        missing = await client.patch("/api/opportunities/999999", json={"title": "Nepostojeća"})
        assert missing.status_code == 404
        bad_stage = await client.get("/api/opportunities", params={"stage": "nepostojeca"})
        assert bad_stage.status_code == 422
    finally:
        await client.aclose()


# ── 4. RBAC ───────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_rbac_rep_own_customers_only(seeded_db: Engine, seed_data) -> None:
    """A rep writes only their own customers' opportunities; finance is read-only."""
    rep_user = next(u for u in seed_data.app_users if u["role"] == "sales_rep")
    rep_client = make_client()
    finance_client = make_client()
    try:
        await login(rep_client, rep_user["email"])
        await login(finance_client, FINANCE_EMAIL)

        with seeded_db.connect() as conn:
            own = conn.execute(
                text(
                    "SELECT customer_id FROM (SELECT DISTINCT ON (customer_id) "
                    "customer_id, sales_rep_id "
                    "FROM core.customer_rep ORDER BY customer_id, from_date DESC) cur "
                    "WHERE sales_rep_id = :rep LIMIT 1"
                ),
                {"rep": rep_user["sales_rep_id"]},
            ).scalar()
            foreign = conn.execute(
                text(
                    "SELECT customer_id FROM (SELECT DISTINCT ON (customer_id) "
                    "customer_id, sales_rep_id "
                    "FROM core.customer_rep ORDER BY customer_id, from_date DESC) cur "
                    "WHERE sales_rep_id != :rep LIMIT 1"
                ),
                {"rep": rep_user["sales_rep_id"]},
            ).scalar()

        # Own customer → allowed; owner_rep_id forced to the rep.
        allowed = await rep_client.post(
            "/api/opportunities", json={"customer_id": own, "title": "Prilika mog kupca"}
        )
        assert allowed.status_code == 201, allowed.text
        assert allowed.json()["owner_rep_id"] == rep_user["sales_rep_id"]
        created_id = allowed.json()["id"]

        # Foreign customer → 403.
        denied = await rep_client.post(
            "/api/opportunities", json={"customer_id": foreign, "title": "Tuđi kupac"}
        )
        assert denied.status_code == 403

        # Finance cannot create; can read.
        finance_create = await finance_client.post(
            "/api/opportunities", json={"customer_id": own, "title": "Finansije ne pišu"}
        )
        assert finance_create.status_code == 403
        assert (await finance_client.get("/api/opportunities")).status_code == 200

        with Session(seeded_db) as session:
            session.execute(
                text("DELETE FROM app.opportunity_stage_history WHERE opportunity_id = :id"),
                {"id": created_id},
            )
            session.execute(text("DELETE FROM app.opportunity WHERE id = :id"), {"id": created_id})
            session.commit()
    finally:
        await rep_client.aclose()
        await finance_client.aclose()


@pytest.mark.anyio
async def test_rbac_rep_list_scoped(seeded_db: Engine, seed_data) -> None:
    """A rep's list returns only their own customers' opportunities."""
    rep_user = next(u for u in seed_data.app_users if u["role"] == "sales_rep")
    rep_client = make_client()
    try:
        await login(rep_client, rep_user["email"])
        items = (await rep_client.get("/api/opportunities")).json()["items"]

        with seeded_db.connect() as conn:
            own_customers = {
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT customer_id FROM (SELECT DISTINCT ON (customer_id) "
                        "customer_id, sales_rep_id "
                        "FROM core.customer_rep ORDER BY customer_id, from_date DESC) cur "
                        "WHERE sales_rep_id = :rep"
                    ),
                    {"rep": rep_user["sales_rep_id"]},
                )
            }
        for item in items:
            assert item["customer_id"] in own_customers
    finally:
        await rep_client.aclose()


# ── 5. kanban columns ─────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_pipeline_kanban_columns(seeded_db: Engine) -> None:
    client = make_client()
    try:
        await login(client, OWNER_EMAIL)
        body = (await client.get("/api/opportunities/pipeline")).json()
        stages = [column["stage"] for column in body["stages"]]
        assert stages == ["lead", "qualified", "proposal", "negotiation", "won", "lost"]
        for column in body["stages"]:
            assert column["count"] == len(column["opportunities"])
    finally:
        await client.aclose()
