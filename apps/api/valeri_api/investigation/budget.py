"""Hard budget caps for the agent loop (M13).

All caps live in app.rule_config (rule='investigation') — never hard-coded. The
caps are checked deterministically between nodes; when any cap is hit, the agent
synthesizes from what it has instead of looping further (D3).
"""

import time
from typing import Any

from sqlalchemy.orm import Session

from valeri_api.rules.engine import load_rule_config


def load_budget(session: Session) -> dict[str, Any]:
    """The investigation caps from rule_config (seeded by migration 0014)."""
    config = load_rule_config(session, "investigation")
    return {
        "max_steps": int(config["max_steps"]),
        "max_seconds": int(config["max_seconds"]),
        "max_tokens": int(config["max_tokens"]),
    }


def over_budget(state: dict[str, Any], budget: dict[str, Any]) -> str | None:
    """Which cap (if any) the run has hit. Deterministic — no model involvement."""
    if state.get("act_count", 0) >= budget["max_steps"]:
        return "max_steps"
    if state.get("tokens_used", 0) >= budget["max_tokens"]:
        return "max_tokens"
    started = state.get("started_ts")
    if started is not None and (time.time() - float(started)) >= budget["max_seconds"]:
        return "max_seconds"
    return None
