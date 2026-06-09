"""Request gates (P2): per-user rate limiting + CSRF double-submit.

Both are env-toggled (RATE_LIMIT_ENABLED / CSRF_ENABLED) and read settings per
request, so tests can flip them without rebuilding the app. In-process token
buckets are deliberate: one api container serves the pilot (spec scope).
"""

import time

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from valeri_api.auth.tokens import COOKIE_NAME
from valeri_api.config import get_settings

CSRF_COOKIE = "valeri_csrf"

# Paths exempt from both gates (liveness must never be throttled; login ISSUES
# the csrf token so it cannot require one).
_RATE_EXEMPT_PREFIXES = ("/api/health",)
_CSRF_EXEMPT_PATHS = ("/api/auth/login", "/api/health")
_MUTATING_METHODS = ("POST", "PUT", "PATCH", "DELETE")


class _TokenBuckets:
    """Minute-window token buckets keyed by (bucket_class, identity)."""

    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], list[float]] = {}

    def allow(self, bucket: str, identity: str, per_minute: int) -> bool:
        now = time.monotonic()
        key = (bucket, identity)
        window = [stamp for stamp in self._hits.get(key, []) if now - stamp < 60.0]
        if len(window) >= per_minute:
            self._hits[key] = window
            return False
        window.append(now)
        self._hits[key] = window
        return True

    def reset(self) -> None:
        self._hits.clear()


rate_limiter = _TokenBuckets()


def _identity(request: Request) -> str:
    """The session cookie when present (per-user), else the client IP."""
    session = request.cookies.get(COOKIE_NAME)
    if session:
        return f"s:{session[-24:]}"
    client = request.client
    return f"ip:{client.host}" if client else "ip:unknown"


def _bucket_for(request: Request) -> tuple[str, int]:
    settings = get_settings()
    path = request.url.path
    if path == "/api/auth/login":
        return "login", settings.rate_limit_login_per_minute
    if (
        request.method == "POST"
        and path.startswith("/api/chat/sessions/")
        and path.endswith("/messages")
    ):
        return "chat", settings.rate_limit_chat_per_minute
    return "default", settings.rate_limit_default_per_minute


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        settings = get_settings()
        if not settings.rate_limit_enabled or request.url.path.startswith(_RATE_EXEMPT_PREFIXES):
            return await call_next(request)

        bucket, per_minute = _bucket_for(request)
        identity = _identity(request) if bucket != "login" else _ip(request)
        if not rate_limiter.allow(bucket, identity, per_minute):
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "rate_limited",
                        "message": "Previše zahtjeva — pokušajte ponovo za minutu.",
                        "details": {"bucket": bucket},
                    }
                },
            )
        return await call_next(request)


def _ip(request: Request) -> str:
    client = request.client
    return f"ip:{client.host}" if client else "ip:unknown"


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double-submit check: mutations must echo the csrf cookie in a header."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        settings = get_settings()
        if (
            not settings.csrf_enabled
            or request.method not in _MUTATING_METHODS
            or request.url.path in _CSRF_EXEMPT_PATHS
            or not request.url.path.startswith("/api/")
        ):
            return await call_next(request)

        cookie = request.cookies.get(CSRF_COOKIE)
        header = request.headers.get("X-CSRF-Token")
        if not cookie or not header or cookie != header:
            return JSONResponse(
                status_code=403,
                content={
                    "error": {
                        "code": "csrf_failed",
                        "message": "Nedostaje ili ne odgovara CSRF token.",
                        "details": {},
                    }
                },
            )
        return await call_next(request)
