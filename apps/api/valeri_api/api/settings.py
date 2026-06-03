"""Settings API (M8): rule-config thresholds + user management + LLM routing (M12)
— per docs/api-spec.md.

rule-config: owner+admin read, admin writes. Threshold changes are how detection
behaviour is tuned — they live in the DB, never in code (CLAUDE.md), and every
change writes an append-only reversible app.decision (M10).
users: admin only.
llm (M12): routing config (role→tier, cascade); masking is shown locked-on and can
never be disabled through the API.
"""

import json
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from valeri_api.audit.decision import log_decision
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
    """Update thresholds; every change records updated_by AND writes a reversible
    app.decision carrying the old value (the M10 decision-audit contract)."""
    import json

    for change in body.changes:
        # Capture the previous value first — it makes the decision reversible
        # and doubles as the existence check.
        old_value = session.execute(
            text("SELECT value FROM app.rule_config WHERE rule = :rule AND param = :param"),
            {"rule": change.rule, "param": change.param},
        ).scalar()
        if old_value is None:
            session.rollback()
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "not_found",
                    "message": f"Unknown threshold {change.rule}.{change.param}",
                },
            )

        session.execute(
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
        log_decision(
            session,
            kind="threshold_change",
            actor="user",
            summary=(
                f"Prag {change.rule}.{change.param} promijenjen "
                f"sa {old_value} na {change.value}"
            ),
            payload={
                "rule": change.rule,
                "param": change.param,
                "old_value": old_value,
                "new_value": change.value,
                "changed_by": user.id,
                "source": "settings",
            },
            reversible=True,
        )
    session.commit()
    return get_rule_config(session, user)


# ── LLM routing settings (M12) ────────────────────────────────────────────────


class LlmTierInfo(BaseModel):
    """One tier as the app sees it; the alias→Claude-model mapping is infra config."""

    alias: str
    description: str


class LlmSettingsResponse(BaseModel):
    provider: str
    tiers: dict[str, LlmTierInfo]
    role_tiers: dict[str, str]
    escalation_confidence_threshold: float
    cascade_enabled: bool
    cascade_max_escalations: int
    # Masking is load-bearing (principle 6) — it is displayed, never configurable.
    masking: Literal["locked_on"] = "locked_on"


class LlmSettingsPatch(BaseModel):
    """Editable routing settings. extra='forbid': any attempt to touch masking
    (or any unknown field) is rejected with 422 — masking cannot be disabled."""

    model_config = ConfigDict(extra="forbid")

    role_tiers: dict[str, str] | None = None
    escalation_confidence_threshold: float | None = Field(default=None, ge=0, le=1)
    cascade_enabled: bool | None = None


def _llm_settings_response(session: Session) -> LlmSettingsResponse:
    from valeri_api.config import get_settings
    from valeri_api.llm.router.router import load_router_config

    config = load_router_config(session)
    settings = get_settings()
    return LlmSettingsResponse(
        provider="anthropic (hosted Claude via LiteLLM)",
        tiers={
            "tier1": LlmTierInfo(
                alias=settings.llm_tier1_alias, description="Claude Haiku — brzi/jeftini sloj"
            ),
            "tier2": LlmTierInfo(
                alias=settings.llm_tier2_alias, description="Claude Sonnet — jaki sloj"
            ),
            "tier2_strong": LlmTierInfo(
                alias=settings.llm_tier2_strong_alias,
                description="Claude Opus — najjači sloj (najteži slučajevi)",
            ),
        },
        role_tiers=config["role_tiers"],
        escalation_confidence_threshold=config["escalation_confidence_threshold"],
        cascade_enabled=config["cascade_enabled"],
        cascade_max_escalations=config["cascade_max_escalations"],
    )


@router.get("/settings/llm", response_model=LlmSettingsResponse)
def get_llm_settings(
    session: Annotated[Session, Depends(get_session)],
    _user: Annotated[object, Depends(require_roles("owner", "admin"))],
) -> LlmSettingsResponse:
    """The LLM routing configuration (per docs/api-spec.md M12)."""
    return _llm_settings_response(session)


@router.patch("/settings/llm", response_model=LlmSettingsResponse)
def patch_llm_settings(
    body: LlmSettingsPatch,
    session: Annotated[Session, Depends(get_session)],
    user: Annotated[AppUser, Depends(require_roles("admin"))],
) -> LlmSettingsResponse:
    """Change routing config; every change writes a reversible app.decision.

    Masking is structurally absent from the patch schema (extra='forbid') — there
    is no path to disable it.
    """
    from valeri_api.llm.router.roles import TIER_ORDER
    from valeri_api.llm.router.router import load_router_config

    config = load_router_config(session)

    # (param, old, new) for every requested change.
    changes: list[tuple[str, Any, Any]] = []
    if body.role_tiers is not None:
        for role, tier in body.role_tiers.items():
            if tier not in TIER_ORDER:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "invalid_tier",
                        "message": f"Nepoznat tier {tier!r} za ulogu {role!r}",
                    },
                )
        changes.append(("role_tiers", config["role_tiers"], body.role_tiers))
    if body.escalation_confidence_threshold is not None:
        changes.append(
            (
                "escalation_confidence_threshold",
                config["escalation_confidence_threshold"],
                body.escalation_confidence_threshold,
            )
        )
    if body.cascade_enabled is not None:
        changes.append(("cascade_enabled", config["cascade_enabled"], body.cascade_enabled))

    for param, old_value, new_value in changes:
        session.execute(
            text(
                "UPDATE app.rule_config "
                "SET value = CAST(:value AS jsonb), updated_by = :user_id, updated_at = now() "
                "WHERE rule = 'llm_router' AND param = :param"
            ),
            {"value": json.dumps(new_value), "user_id": user.id, "param": param},
        )
        log_decision(
            session,
            kind="threshold_change",
            actor="user",
            summary=f"LLM routing: {param} promijenjen",
            payload={
                "rule": "llm_router",
                "param": param,
                "old_value": old_value,
                "new_value": new_value,
                "changed_by": user.id,
                "source": "settings",
            },
            reversible=True,
        )

    session.commit()
    return _llm_settings_response(session)


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
