"""Session tokens: JWT carried in an httpOnly cookie (M8 D1).

The cookie name and lifetime are fixed here; the signing secret comes from the
environment (AUTH_SECRET) — never from code.
"""

import datetime

import jwt

from valeri_api.config import get_settings

COOKIE_NAME = "valeri_session"
_ALGORITHM = "HS256"


class TokenInvalid(Exception):
    """The token is missing, expired, or fails verification."""


def create_token(user_id: int, role: str) -> str:
    """Signed session token for a logged-in user."""
    settings = get_settings()
    now = datetime.datetime.now(datetime.UTC)
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": now,
        "exp": now + datetime.timedelta(hours=settings.auth_token_hours),
    }
    return jwt.encode(payload, settings.auth_secret, algorithm=_ALGORITHM)


def decode_token(raw: str) -> dict:
    """Verify + decode a session token. Raises TokenInvalid."""
    try:
        return jwt.decode(raw, get_settings().auth_secret, algorithms=[_ALGORITHM])
    except jwt.PyJWTError as error:
        raise TokenInvalid(str(error)) from error
