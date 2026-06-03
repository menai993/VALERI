"""Stakes classification (CI1, §8.2): how careful must we be before writing?

Low-stakes + high-confidence + resolved → auto-save. High-stakes (payment,
complaint, negative claim, relationships, large stated value) → confirmation
queue. Thresholds live in app.rule_config (rule='kb'), never in code.
"""

from sqlalchemy.orm import Session

from valeri_api.rules.engine import load_rule_config

# Fact types that are consequential by nature (the user's safety net, tunable below).
_HIGH_STAKES_PREFIXES = ("payment", "complaint", "churn", "negative", "risk", "debt")


def classify_stakes(
    session: Session,
    *,
    item_type: str,
    fact_type: str | None = None,
    value_amount: float | None = None,
    extracted_stakes: str = "low",
) -> str:
    """Return 'high' or 'low'. Relationships are always high (consequential edges)."""
    config = load_rule_config(session, "kb")

    if item_type == "relationship":
        return "high"
    if config.get("high_stakes_always_confirm", True) and extracted_stakes == "high":
        return "high"
    if fact_type and any(fact_type.lower().startswith(p) for p in _HIGH_STAKES_PREFIXES):
        return "high"
    if value_amount is not None and float(value_amount) >= float(config["high_stakes_value"]):
        return "high"
    return "low"
