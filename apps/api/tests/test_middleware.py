"""P2 middleware: rate limiting (chat/login/default buckets) + CSRF + renewal.

Both gates are env-toggled OFF for the rest of the suite (conftest) and enabled
per-test here via monkeypatch (the autouse cache-clear fixture makes settings
re-read per test). Buckets are reset between tests.
"""

import datetime

import pytest
from sqlalchemy import Engine

from tests.conftest import login, make_client
from valeri_api.seed.users import DEV_PASSWORD, OWNER_EMAIL


@pytest.fixture()
def limits_on(monkeypatch):
    """Enable rate limiting with tiny limits and a clean bucket state."""
    from valeri_api.middleware import rate_limiter

    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_LOGIN_PER_MINUTE", "2")
    monkeypatch.setenv("RATE_LIMIT_CHAT_PER_MINUTE", "2")
    monkeypatch.setenv("RATE_LIMIT_DEFAULT_PER_MINUTE", "1000")
    rate_limiter.reset()
    yield
    rate_limiter.reset()


@pytest.fixture()
def csrf_on(monkeypatch):
    monkeypatch.setenv("CSRF_ENABLED", "true")
    yield


@pytest.mark.anyio
async def test_login_throttle(seeded_db: Engine, limits_on) -> None:
    """The 3rd login attempt within the window (limit 2) gets a 429 envelope."""
    client = make_client()
    try:
        for _ in range(2):
            response = await client.post(
                "/api/auth/login", json={"email": OWNER_EMAIL, "password": "wrong"}
            )
            assert response.status_code == 401
        throttled = await client.post(
            "/api/auth/login", json={"email": OWNER_EMAIL, "password": "wrong"}
        )
        assert throttled.status_code == 429
        assert throttled.json()["error"]["code"] == "rate_limited"
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_chat_rate_limit(seeded_db: Engine, limits_on) -> None:
    """Chat messages over the per-user limit get 429; other endpoints unaffected."""
    client = make_client()
    try:
        await login(client, OWNER_EMAIL)
        session_id = (await client.post("/api/chat/sessions")).json()["session_id"]

        for _ in range(2):
            ok = await client.post(
                f"/api/chat/sessions/{session_id}/messages", json={"text": "zdravo"}
            )
            assert ok.status_code == 200
        throttled = await client.post(
            f"/api/chat/sessions/{session_id}/messages", json={"text": "zdravo"}
        )
        assert throttled.status_code == 429

        # The default bucket is generous — normal endpoints still respond.
        assert (await client.get("/api/inbox/summary")).status_code == 200
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_csrf_required_on_mutations(seeded_db: Engine, csrf_on) -> None:
    """POST without X-CSRF-Token → 403; with the cookie's token → passes; GET free."""
    client = make_client()
    try:
        # Login is exempt (it ISSUES the token) and sets the csrf cookie.
        response = await client.post(
            "/api/auth/login", json={"email": OWNER_EMAIL, "password": DEV_PASSWORD}
        )
        assert response.status_code == 200
        csrf = client.cookies.get("valeri_csrf")
        assert csrf, "login must set the non-HttpOnly csrf cookie"

        # GETs are unaffected.
        assert (await client.get("/api/inbox/summary")).status_code == 200

        # A mutation without the header is rejected with the error envelope.
        blocked = await client.post("/api/chat/sessions")
        assert blocked.status_code == 403
        assert blocked.json()["error"]["code"] == "csrf_failed"

        # With the matching header it passes.
        allowed = await client.post("/api/chat/sessions", headers={"X-CSRF-Token": csrf})
        assert allowed.status_code == 201
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_sliding_renewal(seeded_db: Engine) -> None:
    """/auth/me re-issues the session cookie once the token is past half-life."""
    from valeri_api.auth.tokens import COOKIE_NAME, create_token
    from valeri_api.seed.users import OWNER_EMAIL as _owner_email

    client = make_client()
    try:
        await login(client, _owner_email)
        # A fresh token: /auth/me must NOT re-issue.
        fresh = await client.get("/api/auth/me")
        assert "set-cookie" not in {k.lower() for k in fresh.headers}

        # Forge a >half-aged token (7h old of 12h) for the same user.
        user_id = fresh.json()["id"]
        old = create_token(
            user_id,
            "owner",
            issued_at=datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=7),
        )
        client.cookies.set(COOKIE_NAME, old)
        renewed = await client.get("/api/auth/me")
        assert renewed.status_code == 200
        set_cookie = renewed.headers.get("set-cookie", "")
        assert COOKIE_NAME in set_cookie  # silently renewed
    finally:
        await client.aclose()
