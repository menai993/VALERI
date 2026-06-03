"""The graduated-autonomy boundary (M10): auto-apply vs one-tap confirm.

Deterministic code over app.rule_config thresholds — the LLM proposes, but it
NEVER decides whether a rule applies. Customer-facing actions are never-auto by
construction (suppressions/threshold changes are internal); the boundary values
are tunable in the DB, never in code (CLAUDE.md).
"""

from typing import Any, Literal

from sqlalchemy.orm import Session

from valeri_api.rules.engine import load_rule_config
from valeri_api.selfconfig.schemas import EffectEstimate


def decide_autonomy(
    session: Session,
    scope: dict[str, Any],
    effect: EffectEstimate,
    interpretation_confidence: float,
) -> Literal["auto_apply", "requires_confirm"]:
    """Apply the D4 boundary from app.rule_config (rule='selfconfig')."""
    config = load_rule_config(session, "selfconfig")

    confirm_kinds = set(config["confirm_kinds"])
    max_effect = int(config["auto_apply_max_effect"])
    min_confidence = float(config["auto_apply_min_confidence"])

    # Broad/structural kinds always need a human (category, threshold, conditional).
    if scope.get("kind") in confirm_kinds:
        return "requires_confirm"

    # Big blast radius needs a human.
    if effect.total_signals > max_effect:
        return "requires_confirm"

    # A vague interpretation needs a human.
    if interpretation_confidence < min_confidence:
        return "requires_confirm"

    return "auto_apply"
