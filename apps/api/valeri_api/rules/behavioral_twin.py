"""Rule: behavioral_twin_warning — a twin of a churned client showing the same signs (CI2).

Over CONFIRMED behavioral_twin edges: if one twin has already declined
(early_decline) and the other is now stretching its order interval past the
configured ratio, raise an early-warning signal for the at-risk twin, citing the
churned one. Signs come from core.client_expectation (SQL); thresholds in
app.rule_config.
"""

import datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.rules.engine import SignalDraft, load_rule_config

RULE_NAME = "behavioral_twin_warning"


def detect(session: Session, as_of: datetime.date) -> list[SignalDraft]:
    config = load_rule_config(session, RULE_NAME)
    stretch = Decimal(str(config["stretch_ratio"]))
    confidence = Decimal(str(config["conf"]))

    rows = session.execute(
        text(
            "WITH twins AS ("
            "  SELECT from_customer_id AS a, to_customer_id AS b FROM app.client_relationship "
            "  WHERE status = 'active' AND rel_type = 'behavioral_twin' "
            "  UNION "
            "  SELECT to_customer_id AS a, from_customer_id AS b FROM app.client_relationship "
            "  WHERE status = 'active' AND rel_type = 'behavioral_twin'"
            ") "
            "SELECT t.b AS at_risk, t.a AS twin, eb.stretch_ratio AS b_stretch, "
            "       eb.gap_days AS b_gap "
            "FROM twins t "
            "JOIN core.client_expectation ea ON ea.customer_id = t.a "
            "JOIN core.client_expectation eb ON eb.customer_id = t.b "
            "WHERE ea.early_decline = true "
            "  AND eb.stretch_ratio IS NOT NULL AND eb.stretch_ratio >= :stretch"
        ),
        {"stretch": stretch},
    ).all()

    return [
        SignalDraft(
            rule=RULE_NAME,
            customer_id=row.at_risk,
            evidence={
                "twin_customer_id": row.twin,
                "stretch_ratio": str(row.b_stretch),
                "gap_days": row.b_gap,
            },
            confidence=confidence,
            register="preporuka",
        )
        for row in rows
    ]
