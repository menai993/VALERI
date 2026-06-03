"""M8 acceptance: authentication — login/logout/me, cookie behaviour, password hashing.

The session is a JWT in an httpOnly cookie (D1): JavaScript can never read it,
nothing is stored in localStorage, and logout clears it server-side.
"""

import datetime

import pytest
from sqlalchemy import Engine, text

from tests.conftest import login, make_client
from valeri_api.seed.users import DEV_PASSWORD, OWNER_EMAIL


@pytest.mark.anyio
async def test_login_logout_me(seeded_db: Engine) -> None:
    """The full session lifecycle, including the failure paths."""
    client = make_client()
    try:
        # Unauthenticated /auth/me → 401 envelope.
        me = await client.get("/api/auth/me")
        assert me.status_code == 401
        assert "error" in me.json()

        # Wrong password → 401; unknown e-mail → the same 401 (no user enumeration).
        wrong = await client.post(
            "/api/auth/login", json={"email": OWNER_EMAIL, "password": "pogresna-lozinka"}
        )
        unknown = await client.post(
            "/api/auth/login", json={"email": "niko@nigdje.ba", "password": DEV_PASSWORD}
        )
        assert wrong.status_code == 401
        assert unknown.status_code == 401
        assert wrong.json()["error"]["code"] == unknown.json()["error"]["code"]

        # Correct login → 200, user payload, httpOnly cookie set.
        response = await client.post(
            "/api/auth/login", json={"email": OWNER_EMAIL, "password": DEV_PASSWORD}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["user"]["email"] == OWNER_EMAIL
        assert body["user"]["role"] == "owner"
        assert "password" not in str(body).lower() or "password_hash" not in body["user"]

        set_cookie = response.headers.get("set-cookie", "")
        assert "valeri_session=" in set_cookie
        assert "HttpOnly" in set_cookie
        assert "SameSite=lax" in set_cookie or "samesite=lax" in set_cookie.lower()

        # /auth/me with the cookie → the same user.
        me = await client.get("/api/auth/me")
        assert me.status_code == 200
        assert me.json()["email"] == OWNER_EMAIL
        assert me.json()["preferred_language"] == "bs"

        # Logout clears the cookie → /auth/me is 401 again.
        logout = await client.post("/api/auth/logout")
        assert logout.status_code == 204
        me_after = await client.get("/api/auth/me")
        assert me_after.status_code == 401
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_invalid_and_expired_tokens_rejected(seeded_db: Engine, monkeypatch) -> None:
    """Garbage cookies and expired tokens are 401, never 500."""
    client = make_client()
    try:
        # Garbage token.
        client.cookies.set("valeri_session", "nije-pravi-token")
        me = await client.get("/api/auth/me")
        assert me.status_code == 401

        # Expired token: create one that expired an hour ago.
        import jwt as pyjwt

        from valeri_api.config import get_settings

        now = datetime.datetime.now(datetime.UTC)
        expired = pyjwt.encode(
            {
                "sub": "1",
                "role": "owner",
                "iat": now - datetime.timedelta(hours=13),
                "exp": now - datetime.timedelta(hours=1),
            },
            get_settings().auth_secret,
            algorithm="HS256",
        )
        client.cookies.set("valeri_session", expired)
        me = await client.get("/api/auth/me")
        assert me.status_code == 401

        # A token signed with the wrong secret.
        forged = pyjwt.encode(
            {"sub": "1", "role": "owner", "exp": now + datetime.timedelta(hours=1)},
            "neki-drugi-secret",
            algorithm="HS256",
        )
        client.cookies.set("valeri_session", forged)
        me = await client.get("/api/auth/me")
        assert me.status_code == 401
    finally:
        await client.aclose()


def test_passwords_hashed(seeded_db: Engine) -> None:
    """No plaintext password is ever stored; hashes are bcrypt."""
    with seeded_db.connect() as conn:
        rows = conn.execute(text("SELECT email, password_hash FROM app.app_user")).all()

    assert rows, "the seed must create app users"
    for email, password_hash in rows:
        assert password_hash != DEV_PASSWORD, f"{email} stores a plaintext password"
        assert DEV_PASSWORD not in password_hash
        assert password_hash.startswith("$2"), f"{email} hash is not bcrypt"

    # The hash verifies against the dev password (round trip).
    from valeri_api.auth.passwords import verify_password

    assert verify_password(DEV_PASSWORD, rows[0].password_hash)
    assert not verify_password("pogresna-lozinka", rows[0].password_hash)


@pytest.mark.anyio
async def test_seeded_roles_can_all_log_in(seeded_db: Engine, seed_data) -> None:
    """Every seeded user (owner/admin/finance/reps) can authenticate."""
    for user in seed_data.app_users:
        client = make_client()
        try:
            await login(client, user["email"])
            me = await client.get("/api/auth/me")
            assert me.status_code == 200
            assert me.json()["role"] == user["role"]
            assert me.json()["sales_rep_id"] == user["sales_rep_id"]
        finally:
            await client.aclose()
