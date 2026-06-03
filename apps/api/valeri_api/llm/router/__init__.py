"""Role-based LLM routing + cascade escalation (M12)."""

from valeri_api.llm.router.roles import (
    DEFAULT_ROLE_TIERS,
    ROLE_CUSTOMER_DRAFT,
    ROLE_INTENT,
    ROLE_INVESTIGATION,
    ROLE_INVESTIGATION_SYNTHESIS,
    ROLE_NARRATION,
    ROLE_NL_RULE,
    ROLE_OVER_SUPPRESSION_AUDIT,
    ROLE_REPORT_NARRATION,
    ROLE_SIMPLE_QA,
    TIER_ORDER,
)
from valeri_api.llm.router.router import (
    RouteDecision,
    client_for,
    escalate,
    initial_route,
    load_router_config,
)

__all__ = [
    "DEFAULT_ROLE_TIERS",
    "ROLE_CUSTOMER_DRAFT",
    "ROLE_INTENT",
    "ROLE_INVESTIGATION",
    "ROLE_INVESTIGATION_SYNTHESIS",
    "ROLE_NARRATION",
    "ROLE_NL_RULE",
    "ROLE_OVER_SUPPRESSION_AUDIT",
    "ROLE_REPORT_NARRATION",
    "ROLE_SIMPLE_QA",
    "TIER_ORDER",
    "RouteDecision",
    "client_for",
    "escalate",
    "initial_route",
    "load_router_config",
]
