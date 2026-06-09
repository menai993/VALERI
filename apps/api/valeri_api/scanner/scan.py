"""One detection scan: recompute metrics, run every rule, write signals.

The scan consults active app.learned_rule suppressions (the M4 hook; learned
rules themselves are written in M10) and never duplicates open signals.
"""

import datetime
import logging
from types import ModuleType

from pydantic import BaseModel
from sqlalchemy.orm import Session

from valeri_api.metrics.recompute import recompute_all
from valeri_api.rules import (
    behavioral_twin,
    customer_decline,
    group_risk,
    lost_article,
    lost_category,
    narrow_basket,
    referral_risk,
    sleeping_customer,
)
from valeri_api.rules.engine import (
    InsertOutcome,
    insert_signals,
    load_active_suppressions,
    open_signal_keys,
)

logger = logging.getLogger("valeri.scanner")

ALL_RULES: list[ModuleType] = [
    customer_decline,
    lost_article,
    lost_category,
    sleeping_customer,
    narrow_basket,
    # CI2 graph-aware rules — no-op until confirmed relationships + expectations exist.
    group_risk,
    behavioral_twin,
    referral_risk,
]


class ScanResult(BaseModel):
    """What one scan produced, per rule."""

    as_of: datetime.date
    outcomes: dict[str, InsertOutcome]
    tasks_created: int = 0
    # P2 freshness guard: set when the scan refused to run over stale/absent data.
    skipped_reason: str | None = None

    @property
    def total_inserted(self) -> int:
        return sum(outcome.inserted for outcome in self.outcomes.values())

    @property
    def total_suppressed(self) -> int:
        return sum(outcome.suppressed for outcome in self.outcomes.values())


def run_scan(
    session: Session,
    as_of: datetime.date | None = None,
    recompute: bool = True,
    rules: list[ModuleType] | None = None,
    create_tasks: bool = True,
) -> ScanResult:
    """Run all detection rules for the given reference date (default: today).

    With create_tasks=True (the production default), every new signal is turned
    into an assigned task in the same transaction (M5 pipeline).
    """
    reference_date = as_of or datetime.date.today()

    # P2 freshness guard: never scan stale/absent data silently — skip with a
    # recorded reason (threshold ops.scan_stale_days in app.rule_config).
    from valeri_api.ops.runs import data_freshness

    freshness = data_freshness(session)
    if freshness["stale"]:
        reason = (
            "podaci o fakturama stariji od "
            f"{freshness['stale_days_threshold']} dana (zadnja faktura: "
            f"{freshness['last_invoice_date'] or 'nema'})"
        )
        logger.warning("scan skipped: %s", reason)
        return ScanResult(as_of=reference_date, outcomes={}, skipped_reason=reason)

    if recompute:
        recompute_all(session, as_of=reference_date)

    # M11: expiry first — an expired rule must not suppress even one more scan.
    # Lazy import: selfconfig builds on the scanner, not the other way around.
    from valeri_api.selfconfig.auditor import expire_rules

    expire_rules(session)

    suppressions = load_active_suppressions(session)
    existing_keys = open_signal_keys(session)

    outcomes: dict[str, InsertOutcome] = {}
    for rule_module in rules if rules is not None else ALL_RULES:
        drafts = rule_module.detect(session, reference_date)
        outcomes[rule_module.RULE_NAME] = insert_signals(
            session, drafts, suppressions=suppressions, existing_keys=existing_keys
        )

    tasks_created = 0
    if create_tasks:
        # M5: every new signal becomes exactly one assigned task, same transaction.
        from valeri_api.signals.pipeline import create_tasks_from_signals

        tasks_created = create_tasks_from_signals(session, as_of=reference_date).created

    result = ScanResult(as_of=reference_date, outcomes=outcomes, tasks_created=tasks_created)
    logger.info(
        "scan complete as_of=%s inserted=%d suppressed=%d tasks=%d",
        reference_date,
        result.total_inserted,
        result.total_suppressed,
        result.tasks_created,
    )
    return result
