"""Auth API (M8): login / logout / me — session in an httpOnly cookie (D1).

The cookie is HttpOnly + SameSite=Lax: JavaScript never touches the token
(no localStorage, per CLAUDE.md), and the app is same-origin behind Caddy.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from valeri_api.auth.deps import CurrentUser
from valeri_api.auth.models import AppUser
from valeri_api.auth.passwords import verify_password
from valeri_api.auth.schemas import LoginRequest, LoginResponse, UserRead
from valeri_api.auth.tokens import COOKIE_NAME, create_token
from valeri_api.config import get_settings
from valeri_api.db import get_session

router = APIRouter()


@router.post("/auth/login", response_model=LoginResponse)
def login(
    body: LoginRequest,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
) -> LoginResponse:
    """Verify credentials and set the session cookie."""
    user = session.execute(select(AppUser).where(AppUser.email == body.email)).scalar_one_or_none()

    # One generic error for unknown e-mail and wrong password (no user enumeration).
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_credentials", "message": "Pogrešan e-mail ili lozinka"},
        )

    response.set_cookie(
        key=COOKIE_NAME,
        value=create_token(user.id, user.role),
        httponly=True,
        samesite="lax",
        max_age=get_settings().auth_token_hours * 3600,
        path="/",
    )
    return LoginResponse(user=UserRead.model_validate(user))


@router.post("/auth/logout", status_code=204)
def logout(response: Response) -> None:
    """Clear the session cookie."""
    response.delete_cookie(key=COOKIE_NAME, path="/")


@router.get("/auth/me", response_model=UserRead)
def me(user: CurrentUser) -> UserRead:
    """The currently logged-in user (401 when not authenticated)."""
    return UserRead.model_validate(user)
