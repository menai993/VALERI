"""P3 spend guards: per-feature daily caps + the near-cap throttle.

Cheap gate, expensive payload only when warranted (llm-cost.md §6.5). Caps refuse
a feature once it has run N times today; the throttle defers NON-ESSENTIAL roles
(scheduled narration, drafts, the auditor) when month spend nears the budget —
chat and on-demand actions are never throttled. Thresholds live in rule_config.
"""

import datetime
import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.llm.cost import budget_status
from valeri_api.rules.engine import load_rule_config

logger = logging.getLogger("valeri.llm.spend_guard")


def _llm_cost_config(session: Session) -> dict:
    try:
        return load_rule_config(session, "llm_cost")
    except LookupError:  # pragma: no cover — seeded by migration 0025
        return {}


# How a feature's daily usage is counted. The investigation cap limits the number
# of investigation RUNS started today (one run makes many LLM calls, so counting
# ai_log rows would let a single deep run self-trip the cap). Other capped features
# count their own audit.ai_log calls.
_FEATURE_COUNT_SQL = {
    "investigation": "SELECT count(*) FROM app.investigation WHERE created_at::date = :day",
}


def feature_cap_reached(session: Session, feature: str) -> bool:
    """True when `feature` has already reached its daily cap.

    The unit per feature comes from `_FEATURE_COUNT_SQL` (investigation = runs
    started today; everything else = its ai_log calls). The cap value comes from
    rule_config.llm_cost.feature_daily_caps; no cap configured → never blocks.
    """
    caps = _llm_cost_config(session).get("feature_daily_caps", {})
    cap = caps.get(feature)
    if cap is None:
        return False
    today = datetime.date.today()
    count_sql = _FEATURE_COUNT_SQL.get(
        feature, "SELECT count(*) FROM audit.ai_log WHERE feature = :f AND created_at::date = :day"
    )
    count = session.execute(text(count_sql), {"f": feature, "day": today}).scalar_one()
    reached = count >= int(cap)
    if reached:
        logger.info("feature %r hit its daily cap (%s) — refusing", feature, cap)
    return reached


def is_non_essential(session: Session, role: str) -> bool:
    """Whether a role is safe to defer under the near-cap throttle."""
    roles = _llm_cost_config(session).get("non_essential_roles", [])
    return role in roles


def non_essential_throttled(session: Session) -> bool:
    """True when month spend has crossed the throttle threshold (defer non-essential).

    Distinct from the budget *alert* (which fires earlier, at alert_pct): the
    throttle is the harder line at throttle_pct where we stop spending on
    deferrable work. Returns False when there is no budget/limit.
    """
    throttle_pct = int(_llm_cost_config(session).get("throttle_pct", 90))
    status = budget_status(session)
    return status["pct"] is not None and status["pct"] >= throttle_pct
