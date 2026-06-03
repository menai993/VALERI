"""M8 acceptance: settings endpoints — rule-config thresholds + user management."""

import pytest
from sqlalchemy import Engine, text

from tests.conftest import login, make_client
from valeri_api.seed.users import ADMIN_EMAIL


@pytest.mark.anyio
async def test_rule_config_read_and_update(seeded_db: Engine) -> None:
    """GET lists thresholds; PATCH (admin) updates a value, records updated_by AND
    writes a reversible threshold_change decision (the M10 decision-audit contract)."""
    client = make_client()
    try:
        await login(client, ADMIN_EMAIL)

        # All thresholds are listed.
        listing = await client.get("/api/settings/rule-config")
        assert listing.status_code == 200
        items = listing.json()["items"]
        assert items, "rule_config must be seeded by the M4/M5 migrations"
        rules = {item["rule"] for item in items}
        assert "customer_decline" in rules

        # Update one threshold; updated_by is recorded.
        target = next(
            item
            for item in items
            if item["rule"] == "customer_decline" and item["param"] == "task_due_days"
        )
        original_value = target["value"]
        with seeded_db.connect() as conn:
            decisions_before = conn.execute(
                text("SELECT COUNT(*) FROM app.decision WHERE kind = 'threshold_change'")
            ).scalar()
        patched = await client.patch(
            "/api/settings/rule-config",
            json={"changes": [{"rule": "customer_decline", "param": "task_due_days", "value": 5}]},
        )
        assert patched.status_code == 200

        with seeded_db.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT value, updated_by FROM app.rule_config "
                    "WHERE rule = 'customer_decline' AND param = 'task_due_days'"
                )
            ).one()
        assert row.value == 5
        assert row.updated_by is not None

        # The change wrote exactly one reversible threshold_change decision
        # carrying the old value (no silent self-modification).
        with seeded_db.connect() as conn:
            decisions = conn.execute(
                text(
                    "SELECT actor, reversible, payload FROM app.decision "
                    "WHERE kind = 'threshold_change' ORDER BY id DESC"
                )
            ).all()
        assert len(decisions) == decisions_before + 1
        latest = decisions[0]
        assert latest.actor == "user"
        assert latest.reversible is True
        assert latest.payload["rule"] == "customer_decline"
        assert latest.payload["param"] == "task_due_days"
        assert latest.payload["old_value"] == original_value
        assert latest.payload["new_value"] == 5

        # Unknown threshold → 404; restore the original value.
        unknown = await client.patch(
            "/api/settings/rule-config",
            json={"changes": [{"rule": "nepostojece", "param": "x", "value": 1}]},
        )
        assert unknown.status_code == 404

        await client.patch(
            "/api/settings/rule-config",
            json={
                "changes": [
                    {
                        "rule": "customer_decline",
                        "param": "task_due_days",
                        "value": original_value,
                    }
                ]
            },
        )
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_user_management_admin_only(seeded_db: Engine) -> None:
    """Admin can list/create/update users; password hashes never leave the DB."""
    client = make_client()
    try:
        await login(client, ADMIN_EMAIL)

        # List: every user, no password_hash in the payload.
        listing = await client.get("/api/settings/users")
        assert listing.status_code == 200
        users = listing.json()["items"]
        assert len(users) >= 4  # owner + admin + finance + at least one rep
        assert all("password_hash" not in user and "password" not in user for user in users)

        # Create a user.
        created = await client.post(
            "/api/settings/users",
            json={
                "name": "Test Korisnik",
                "email": "test.korisnik@ultrahigijena.ba",
                "role": "finance",
                "password": "sigurna-lozinka-123",
            },
        )
        assert created.status_code == 201
        user_id = created.json()["id"]
        assert created.json()["preferred_language"] == "bs"

        # Duplicate e-mail → 409.
        duplicate = await client.post(
            "/api/settings/users",
            json={
                "name": "Duplikat",
                "email": "test.korisnik@ultrahigijena.ba",
                "role": "finance",
                "password": "sigurna-lozinka-123",
            },
        )
        assert duplicate.status_code == 409

        # The new user can log in.
        new_client = make_client()
        try:
            response = await new_client.post(
                "/api/auth/login",
                json={
                    "email": "test.korisnik@ultrahigijena.ba",
                    "password": "sigurna-lozinka-123",
                },
            )
            assert response.status_code == 200
            assert response.json()["user"]["role"] == "finance"
        finally:
            await new_client.aclose()

        # Update: role + preferred language.
        updated = await client.patch(
            f"/api/settings/users/{user_id}",
            json={"role": "owner", "preferred_language": "en"},
        )
        assert updated.status_code == 200
        assert updated.json()["role"] == "owner"
        assert updated.json()["preferred_language"] == "en"

        # Unknown user → 404.
        missing = await client.patch("/api/settings/users/999999", json={"name": "X"})
        assert missing.status_code == 404

        # Clean up the created user (keep module state predictable).
        with seeded_db.connect() as conn:
            conn.execute(text("DELETE FROM app.app_user WHERE id = :id"), {"id": user_id})
            conn.commit()
    finally:
        await client.aclose()


# ── LLM routing settings (M12) ────────────────────────────────────────────────


@pytest.mark.anyio
async def test_llm_settings_get_and_patch(seeded_db: Engine) -> None:
    """M12: GET shows routing config + locked masking; PATCH (admin) changes role
    tiers/escalation, writes reversible decisions, and the router picks it up."""
    from sqlalchemy.orm import Session

    client = make_client()
    try:
        await login(client, ADMIN_EMAIL)

        # ── GET: the full routing picture ─────────────────────────────────────
        response = await client.get("/api/settings/llm")
        assert response.status_code == 200
        body = response.json()
        assert body["masking"] == "locked_on"
        assert body["provider"].startswith("anthropic")
        assert set(body["tiers"]) == {"tier1", "tier2", "tier2_strong"}
        assert body["role_tiers"]["narration"] == "tier1"
        assert body["role_tiers"]["over_suppression_audit"] == "tier2"
        assert body["cascade_enabled"] is True

        # ── PATCH: the Sonnet→Opus swap for the audit role + tighter escalation ──
        with seeded_db.connect() as conn:
            decisions_before = conn.execute(
                text("SELECT COUNT(*) FROM app.decision WHERE kind = 'threshold_change'")
            ).scalar()

        new_role_tiers = dict(body["role_tiers"])
        new_role_tiers["over_suppression_audit"] = "tier2_strong"
        patched = await client.patch(
            "/api/settings/llm",
            json={"role_tiers": new_role_tiers, "escalation_confidence_threshold": 0.7},
        )
        assert patched.status_code == 200
        assert patched.json()["role_tiers"]["over_suppression_audit"] == "tier2_strong"
        assert patched.json()["escalation_confidence_threshold"] == 0.7

        # Each change wrote one reversible decision (old + new values preserved).
        with seeded_db.connect() as conn:
            decisions_after = conn.execute(
                text("SELECT COUNT(*) FROM app.decision WHERE kind = 'threshold_change'")
            ).scalar()
            latest = conn.execute(
                text(
                    "SELECT reversible, payload FROM app.decision "
                    "WHERE kind = 'threshold_change' ORDER BY id DESC LIMIT 2"
                )
            ).all()
        assert decisions_after == decisions_before + 2
        assert all(row.reversible for row in latest)
        params_changed = {row.payload["param"] for row in latest}
        assert params_changed == {"role_tiers", "escalation_confidence_threshold"}

        # The router immediately routes the audit role to the new tier (config-only swap).
        from valeri_api.llm.router.router import initial_route

        with Session(seeded_db) as session:
            decision = initial_route(session, "over_suppression_audit")
            assert decision.chosen_tier == "tier2_strong"
            session.rollback()  # the route-log row from this check is not needed

        # ── invalid tier → 422 ────────────────────────────────────────────────
        bad = await client.patch("/api/settings/llm", json={"role_tiers": {"narration": "tier99"}})
        assert bad.status_code == 422

        # ── masking cannot be disabled: unknown fields are rejected ──────────
        masked = await client.patch("/api/settings/llm", json={"masking": "off"})
        assert masked.status_code == 422
        masked2 = await client.patch("/api/settings/llm", json={"pii_masking_enabled": False})
        assert masked2.status_code == 422

        # Restore the defaults for other tests.
        await client.patch(
            "/api/settings/llm",
            json={"role_tiers": body["role_tiers"], "escalation_confidence_threshold": 0.6},
        )
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_llm_settings_rbac(seeded_db: Engine) -> None:
    """Owner reads but cannot write; finance/rep can do neither."""
    from valeri_api.seed.users import FINANCE_EMAIL, OWNER_EMAIL

    owner_client = make_client()
    finance_client = make_client()
    try:
        await login(owner_client, OWNER_EMAIL)
        await login(finance_client, FINANCE_EMAIL)

        # Owner: read yes, write no.
        assert (await owner_client.get("/api/settings/llm")).status_code == 200
        owner_patch = await owner_client.patch("/api/settings/llm", json={"cascade_enabled": False})
        assert owner_patch.status_code == 403

        # Finance: neither.
        assert (await finance_client.get("/api/settings/llm")).status_code == 403
        finance_patch = await finance_client.patch(
            "/api/settings/llm", json={"cascade_enabled": False}
        )
        assert finance_patch.status_code == 403
    finally:
        await owner_client.aclose()
        await finance_client.aclose()
