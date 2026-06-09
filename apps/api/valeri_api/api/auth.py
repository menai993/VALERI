"""Auth API (M8): login / logout / me — session in an httpOnly cookie (D1).

The session cookie is HttpOnly + SameSite=Lax: JavaScript never touches the
token (no localStorage, per CLAUDE.md), and the app is same-origin behind
Caddy. P2 adds a non-HttpOnly `valeri_csrf` cookie at login (double-submit:
the SPA echoes it in X-CSRF-Token on mutations) and sliding renewal in
/auth/me so an active user is never logged out mid-day.
"""

import datetime
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from valeri_api.auth.deps import CurrentUser
from valeri_api.auth.models import AppUser
from valeri_api.auth.passwords import verify_password
from valeri_api.auth.schemas import LoginRequest, LoginResponse, UserRead
from valeri_api.auth.tokens import COOKIE_NAME, TokenInvalid, create_token, decode_token
from valeri_api.config import get_settings
from valeri_api.db import get_session
from valeri_api.middleware import CSRF_COOKIE

router = APIRouter()


def _set_session_cookies(response: Response, user_id: int, role: str) -> None:
    """Session (HttpOnly) + csrf (readable by the SPA) cookies, same lifetime."""
    max_age = get_settings().auth_token_hours * 3600
    response.set_cookie(
        key=COOKIE_NAME,
        value=create_token(user_id, role),
        httponly=True,
        samesite="lax",
        max_age=max_age,
        path="/",
    )
    response.set_cookie(
        key=CSRF_COOKIE,
        value=secrets.token_urlsafe(32),
        httponly=False,  # double-submit: the SPA must read it back into a header
        samesite="lax",
        max_age=max_age,
        path="/",
    )


@router.post("/auth/login", response_model=LoginResponse)
def login(
    body: LoginRequest,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
) -> LoginResponse:
    """Verify credentials and set the session + csrf cookies."""
    user = session.execute(select(AppUser).where(AppUser.email == body.email)).scalar_one_or_none()

    # One generic error for unknown e-mail and wrong password (no user enumeration).
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_credentials", "message": "Pogrešan e-mail ili lozinka"},
        )

    _set_session_cookies(response, user.id, user.role)
    return LoginResponse(user=UserRead.model_validate(user))


@router.post("/auth/logout", status_code=204)
def logout(response: Response) -> None:
    """Clear the session cookies."""
    response.delete_cookie(key=COOKIE_NAME, path="/")
    response.delete_cookie(key=CSRF_COOKIE, path="/")


@router.get("/auth/me", response_model=UserRead)
def me(user: CurrentUser, request: Request, response: Response) -> UserRead:
    """The currently logged-in user (401 when not authenticated).

    Sliding renewal: once the token is past half-life, re-issue the cookies so
    an active session never expires under the user. Fresh tokens set nothing.
    """
    raw = request.cookies.get(COOKIE_NAME)
    if raw:
        try:
            issued = decode_token(raw)["iat"]
            age = datetime.datetime.now(datetime.UTC).timestamp() - issued
            if age > get_settings().auth_token_hours * 3600 / 2:
                _set_session_cookies(response, user.id, user.role)
        except TokenInvalid:  # pragma: no cover — CurrentUser already 401s
            pass
    return UserRead.model_validate(user)
