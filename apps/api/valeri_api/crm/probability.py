"""Stage probabilities + stage classification (C-CRM1).

The stage→default-probability map lives in app.rule_config (rule='crm') — tunable,
never hard-coded. An opportunity's explicit probability overrides its stage default;
this module is the single source of truth for both the SQL aggregation and the API.
"""

from sqlalchemy.orm import Session

from valeri_api.rules.engine import load_rule_config

# Open stages carry pipeline (weighted) value; closed stages are won/lost.
OPEN_STAGES = ("lead", "qualified", "proposal", "negotiation")
CLOSED_STAGES = ("won", "lost")
ALL_STAGES = OPEN_STAGES + CLOSED_STAGES

# Activity kinds (data-model.md: app.activity.kind) — C-CRM2.
ACTIVITY_KINDS = ("meeting", "call", "offer", "follow_up", "analysis")


def stage_probabilities(session: Session) -> dict[str, float]:
    """The stage→default-probability map from rule_config (seeded by migration 0016)."""
    config = load_rule_config(session, "crm")
    return {stage: float(p) for stage, p in dict(config["stage_probability"]).items()}
