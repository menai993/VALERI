"""Blast-radius estimation (M10): how much would a scope suppress? Pure SQL.

The predicted effect shown on the confirm card and stored on the learned rule is
a SQL count over historical signals — never an LLM guess (principle 1).
"""

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.rules.engine import load_rule_config
from valeri_api.selfconfig.schemas import EffectEstimate

# One query handles every scope kind via NULL-guarded filters; all values are binds.
_EFFECT_SQL = """
SELECT s.rule, COUNT(*) AS n
FROM app.signal s
LEFT JOIN core.customer c ON c.id = s.customer_id
WHERE s.created_at > now() - make_interval(days => :window_days)
  AND (CAST(:rule AS text) IS NULL OR s.rule = :rule)
  AND (CAST(:customer_id AS bigint) IS NULL OR s.customer_id = :customer_id)
  AND (CAST(:article_id AS bigint) IS NULL OR s.article_id = :article_id)
  AND (CAST(:segment AS text) IS NULL OR c.segment = :segment)
GROUP BY s.rule
"""


def estimate_effect(session: Session, scope: dict[str, Any]) -> EffectEstimate:
    """Count the signals (last N days) this scope would have suppressed, by rule."""
    config = load_rule_config(session, "selfconfig")
    window_days = int(config["effect_window_days"])

    customer_id = None
    article_id = None
    if scope.get("kind") in ("entity", "once"):
        if scope.get("entity_type") == "customer":
            customer_id = scope.get("entity_id") or scope.get("customer_id")
        elif scope.get("entity_type") == "article":
            article_id = scope.get("entity_id") or scope.get("article_id")
        else:
            customer_id = scope.get("customer_id")
            article_id = scope.get("article_id")

    rows = session.execute(
        text(_EFFECT_SQL),
        {
            "window_days": window_days,
            "rule": scope.get("rule"),
            "customer_id": customer_id,
            "article_id": article_id,
            # Category scopes match the customer segment (find_suppression semantics).
            "segment": scope.get("category") if scope.get("kind") == "category" else None,
        },
    ).all()

    by_rule = {row.rule: row.n for row in rows}
    return EffectEstimate(
        window_days=window_days,
        total_signals=sum(by_rule.values()),
        by_rule=by_rule,
    )
