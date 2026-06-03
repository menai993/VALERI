"""Settings API (M8): rule-config thresholds + user management — per docs/api-spec.md.

rule-config: owner+admin read, admin writes (every change records updated_by).
users: admin only. Threshold changes are how detection behaviour is tuned —
they live in the DB, never in code (CLAUDE.md).
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from valeri_api.auth.deps import require_roles
from valeri_api.auth.models import AppUser
from valeri_api.auth.passwords import hash_password
from valeri_api.auth.schemas import UserCreate, UserListResponse, UserRead, UserUpdate
from valeri_api.db import get_session

router = APIRouter()


class RuleConfigEntry(BaseModel):
    rule: str
    param: str
    value: Any
    updated_by: int | None = None
    updated_at: str | None = None


class RuleConfigResponse(BaseModel):
    items: list[RuleConfigEntry]


class RuleConfigPatch(BaseModel):
    """One threshold change: (rule, param) → new value."""

    rule: str
    param: str
    value: Any


class RuleConfigPatchRequest(BaseModel):
    changes: list[RuleConfigPatch]


# ── rule-config (thresholds) ──────────────────────────────────────────────────


@router.get("/settings/rule-config", response_model=RuleConfigResponse)
def get_rule_config(
    session: Annotated[Session, Depends(get_session)],
    _user: Annotated[object, Depends(require_roles("owner", "admin"))],
) -> RuleConfigResponse:
    """All detection thresholds (app.rule_config)."""
    rows = session.execute(
        text(
            "SELECT rule, param, value, updated_by, updated_at::text AS updated_at "
            "FROM app.rule_config ORDER BY rule, param"
        )
    ).mappings()
    return RuleConfigResponse(items=[RuleConfigEntry(**dict(row)) for row in rows])


@router.patch("/settings/rule-config", response_model=RuleConfigResponse)
def patch_rule_config(
    body: RuleConfigPatchRequest,
    session: Annotated[Session, Depends(get_session)],
    user: Annotated[AppUser, Depends(require_roles("admin"))],
) -> RuleConfigResponse:
    """Update thresholds; every change records who made it (updated_by)."""
    import json

    for change in body.changes:
        result = session.execute(
            text(
                "UPDATE app.rule_config "
                "SET value = CAST(:value AS jsonb), updated_by = :user_id, updated_at = now() "
                "WHERE rule = :rule AND param = :param"
            ),
            {
                "value": json.dumps(change.value),
                "user_id": user.id,
                "rule": change.rule,
                "param": change.param,
            },
        )
        if result.rowcount == 0:
            session.rollback()
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "not_found",
                    "message": f"Unknown threshold {change.rule}.{change.param}",
                },
            )
    session.commit()
    return get_rule_config(session, user)


# ── users (admin only) ────────────────────────────────────────────────────────


def _user_not_found(user_id: int) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"code": "not_found", "message": f"User {user_id} not found"},
    )


@router.get("/settings/users", response_model=UserListResponse)
def list_users(
    session: Annotated[Session, Depends(get_session)],
    _admin: Annotated[AppUser, Depends(require_roles("admin"))],
) -> UserListResponse:
    """All application users (password hashes never leave the database)."""
    users = session.execute(select(AppUser).order_by(AppUser.id)).scalars()
    return UserListResponse(items=[UserRead.model_validate(user) for user in users])


@router.post("/settings/users", status_code=201, response_model=UserRead)
def create_user(
    body: UserCreate,
    session: Annotated[Session, Depends(get_session)],
    _admin: Annotated[AppUser, Depends(require_roles("admin"))],
) -> UserRead:
    """Create a user (password is hashed, never stored in plaintext)."""
    existing = session.execute(
        select(AppUser).where(AppUser.email == body.email)
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail={"code": "conflict", "message": f"User {body.email} already exists"},
        )

    user = AppUser(
        name=body.name,
        email=body.email,
        role=body.role,
        password_hash=hash_password(body.password),
        sales_rep_id=body.sales_rep_id,
        preferred_language=body.preferred_language,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return UserRead.model_validate(user)


@router.patch("/settings/users/{user_id}", response_model=UserRead)
def update_user(
    user_id: int,
    body: UserUpdate,
    session: Annotated[Session, Depends(get_session)],
    _admin: Annotated[AppUser, Depends(require_roles("admin"))],
) -> UserRead:
    """Update a user; a new password is re-hashed."""
    user = session.get(AppUser, user_id)
    if user is None:
        raise _user_not_found(user_id)

    if body.name is not None:
        user.name = body.name
    if body.role is not None:
        user.role = body.role
    if body.password is not None:
        user.password_hash = hash_password(body.password)
    if body.sales_rep_id is not None:
        user.sales_rep_id = body.sales_rep_id
    if body.preferred_language is not None:
        user.preferred_language = body.preferred_language

    session.commit()
    session.refresh(user)
    return UserRead.model_validate(user)
