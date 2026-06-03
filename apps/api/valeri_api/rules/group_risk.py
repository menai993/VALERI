"""Rule: group_risk — owner/group/chain objects declining TOGETHER (CI2).

Over CONFIRMED same_owner/same_group/chain edges, treat the connected objects as
one group: if the group's combined turnover has fallen below the configured ratio
of its combined baseline, raise one signal anchored on the most-at-risk member,
with all members in the evidence. Components come from graph traversal; every
NUMBER (combined turnover/baseline/ratio, the worst member) is SQL. Thresholds in
app.rule_config.
"""

import datetime
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.kb.graph import GROUP_REL_TYPES, connected_components
from valeri_api.rules.engine import SignalDraft, load_rule_config

RULE_NAME = "group_risk"


def detect(session: Session, as_of: datetime.date) -> list[SignalDraft]:
    config = load_rule_config(session, RULE_NAME)
    decline_ratio = Decimal(str(config["decline_ratio"]))
    min_members = int(config["min_members"])
    confidence = Decimal(str(config["conf"]))

    drafts: list[SignalDraft] = []
    for members in connected_components(session, GROUP_REL_TYPES):
        if len(members) < min_members:
            continue
        # Combined turnover/baseline/ratio + the worst-ratio member — all SQL.
        row = session.execute(
            text(
                "SELECT SUM(turnover_60d) AS turnover, "
                "       SUM(turnover_6m_avg_60d) AS baseline, "
                "       ROUND(SUM(turnover_60d) / "
                "             NULLIF(SUM(turnover_6m_avg_60d), 0), 3) AS ratio, "
                "       (ARRAY_AGG(customer_id ORDER BY "
                "          turnover_60d / NULLIF(turnover_6m_avg_60d, 0) ASC))[1] AS worst "
                "FROM core.customer_metrics "
                "WHERE customer_id = ANY(:ids) AND turnover_6m_avg_60d > 0"
            ),
            {"ids": sorted(members)},
        ).one()

        if row.ratio is None or row.worst is None:
            continue
        if row.ratio >= decline_ratio:
            continue

        drafts.append(
            SignalDraft(
                rule=RULE_NAME,
                customer_id=row.worst,
                evidence={
                    "members": sorted(members),
                    "group_turnover_60d": str(row.turnover),
                    "group_baseline_60d": str(row.baseline),
                    "ratio": str(row.ratio),
                    "rel_types": list(GROUP_REL_TYPES),
                },
                confidence=confidence,
                register="preporuka",
            )
        )
    return drafts
