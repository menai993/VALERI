"""The role-based LLM router + cascade escalation (M12).

The router decides WHICH client answers an already-masked prompt — it sits after
masking and before the gateway, and can never touch payload content. Every
decision (initial mapping, escalation, injected test client) is appended to
audit.llm_route_log.

Cascade policy (spec D3): at most `cascade_max_escalations` steps up TIER_ORDER,
triggered by low self-confidence or by validator-reject after the retry budget.
All thresholds live in app.rule_config (rule='llm_router').
"""

import logging
import uuid
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from valeri_api.audit.route_log import log_route
from valeri_api.config import get_settings
from valeri_api.llm.client import LiteLLMClient, LLMClient
from valeri_api.llm.router.roles import DEFAULT_ROLE_TIERS, FALLBACK_TIER, TIER_ORDER
from valeri_api.rules.engine import load_rule_config

logger = logging.getLogger("valeri.llm.router")

# Route reasons (the audit vocabulary).
REASON_ROLE_DEFAULT = "role_default"
REASON_INJECTED_CLIENT = "injected_client"
REASON_LOW_CONFIDENCE = "low_confidence"
REASON_VALIDATOR_REJECT = "validator_reject"


class RouteDecision(BaseModel):
    """One routing decision — what the route log records."""

    request_id: str
    task_role: str
    chosen_tier: str
    model: str
    reason: str
    escalation_count: int = 0


def load_router_config(session: Session) -> dict[str, Any]:
    """The llm_router thresholds from app.rule_config (seeded by migration 0013)."""
    try:
        config = load_rule_config(session, "llm_router")
    except LookupError:
        # Defensive: an unmigrated/cleared DB still routes (to defaults) rather than failing.
        logger.warning("no llm_router rule_config rows; using code defaults")
        config = {}
    return {
        "role_tiers": config.get("role_tiers", DEFAULT_ROLE_TIERS),
        "escalation_confidence_threshold": float(
            config.get("escalation_confidence_threshold", 0.6)
        ),
        "cascade_enabled": bool(config.get("cascade_enabled", True)),
        "cascade_max_escalations": int(config.get("cascade_max_escalations", 1)),
    }


def initial_route(session: Session, role: str, override: LLMClient | None = None) -> RouteDecision:
    """The role→tier decision for one logical request. Always logged."""
    config = load_router_config(session)
    tier = config["role_tiers"].get(role, FALLBACK_TIER)
    decision = RouteDecision(
        request_id=uuid.uuid4().hex,
        task_role=role,
        chosen_tier=tier,
        model=getattr(override, "model", None) or tier,
        reason=REASON_INJECTED_CLIENT if override is not None else REASON_ROLE_DEFAULT,
    )
    log_route(
        session,
        request_id=decision.request_id,
        task_role=decision.task_role,
        chosen_tier=decision.chosen_tier,
        model=decision.model,
        reason=decision.reason,
    )
    return decision


def escalate(
    session: Session,
    decision: RouteDecision,
    reason: str,
    confidence: float | None = None,
    override: LLMClient | None = None,
) -> RouteDecision | None:
    """One cascade step up TIER_ORDER, or None when escalation is not allowed.

    Not allowed when: cascade disabled, the cap is reached, or there is no
    higher tier. The escalation itself is logged with its trigger + the
    confidence that caused it.
    """
    config = load_router_config(session)
    if not config["cascade_enabled"]:
        return None
    if decision.escalation_count >= config["cascade_max_escalations"]:
        return None

    try:
        current_index = TIER_ORDER.index(decision.chosen_tier)
    except ValueError:
        return None
    if current_index + 1 >= len(TIER_ORDER):
        return None  # already at the strongest tier

    next_tier = TIER_ORDER[current_index + 1]
    escalated = RouteDecision(
        request_id=decision.request_id,  # same logical request
        task_role=decision.task_role,
        chosen_tier=next_tier,
        model=getattr(override, "model", None) or next_tier,
        reason=reason,
        escalation_count=decision.escalation_count + 1,
    )
    log_route(
        session,
        request_id=escalated.request_id,
        task_role=escalated.task_role,
        chosen_tier=escalated.chosen_tier,
        model=escalated.model,
        reason=escalated.reason,
        confidence=confidence,
    )
    logger.info(
        "cascade escalation: role=%s %s → %s (%s)",
        decision.task_role,
        decision.chosen_tier,
        next_tier,
        reason,
    )
    return escalated


def tier_alias(tier: str) -> str:
    """The LiteLLM alias for a tier (settings-level mapping; config-only model swaps)."""
    settings = get_settings()
    aliases = {
        "tier1": settings.llm_tier1_alias,
        "tier2": settings.llm_tier2_alias,
        "tier2_strong": settings.llm_tier2_strong_alias,
    }
    return aliases.get(tier, settings.llm_tier1_alias)


def client_for(decision: RouteDecision, override: LLMClient | None = None) -> LLMClient:
    """The client that serves a routing decision.

    An injected client (tests) is always honoured — routing still gets logged, but
    the override answers every tier (the route log shows what WOULD have been used).
    """
    if override is not None:
        return override
    return LiteLLMClient(model=tier_alias(decision.chosen_tier))


def client_for_route(
    route: RouteDecision,
    override: LLMClient | None,
    factory: Callable[[], LLMClient],
) -> LLMClient:
    """The entry-point variant of client_for: `factory` is the caller's (patchable)
    get_llm_client binding.

    Production clients from the factory are re-pointed at the routed tier's alias;
    a fake returned by a patched factory (tests) is used as-is for every tier —
    routing decisions are still logged either way.
    """
    if override is not None:
        return override
    candidate = factory()
    if isinstance(candidate, LiteLLMClient):
        candidate.model = tier_alias(route.chosen_tier)
    return candidate
