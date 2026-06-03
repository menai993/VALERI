"""M8 acceptance: settings endpoints — rule-config thresholds + user management."""

import pytest
from sqlalchemy import Engine, text

from tests.conftest import login, make_client
from valeri_api.seed.users import ADMIN_EMAIL


@pytest.mark.anyio
async def test_rule_config_read_and_update(seeded_db: Engine) -> None:
    """GET lists thresholds; PATCH (admin) updates a value and records updated_by."""
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
