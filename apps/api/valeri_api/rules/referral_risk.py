"""Rule: referral_source_risk — a quiet referrer puts its referrals at risk (CI2).

Over CONFIRMED referral edges (referrer → referred): if the referrer has gone
quiet (gap since last order ≥ the configured days), raise a signal on each
referred customer, citing the referrer. The gap comes from core.client_expectation
(SQL); the threshold lives in app.rule_config.
"""

import datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.rules.engine import SignalDraft, load_rule_config

RULE_NAME = "referral_source_risk"


def detect(session: Session, as_of: datetime.date) -> list[SignalDraft]:
    config = load_rule_config(session, RULE_NAME)
    quiet_days = int(config["quiet_days"])
    confidence = Decimal(str(config["conf"]))

    rows = session.execute(
        text(
            "SELECT r.to_customer_id AS at_risk, r.from_customer_id AS referrer, "
            "       er.gap_days AS referrer_gap "
            "FROM app.client_relationship r "
            "JOIN core.client_expectation er ON er.customer_id = r.from_customer_id "
            "WHERE r.status = 'active' AND r.rel_type = 'referral' "
            "  AND er.gap_days IS NOT NULL AND er.gap_days >= :quiet"
        ),
        {"quiet": quiet_days},
    ).all()

    return [
        SignalDraft(
            rule=RULE_NAME,
            customer_id=row.at_risk,
            evidence={"referrer_customer_id": row.referrer, "referrer_gap_days": row.referrer_gap},
            confidence=confidence,
            register="preporuka",
        )
        for row in rows
    ]
