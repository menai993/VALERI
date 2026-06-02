"""sleeping_customer rule: labeled cases per docs/rules/sleeping-customer.md.

Cases:
  true_positive               — regular history, silent for 9× their interval → fires, visoka
  must_not_fire (still active) — last order well within their cadence → does NOT fire
  must_not_fire (slow cadence) — absolute gap met but not gap_factor × interval → does NOT fire
  low_confidence_borderline   — gap exactly at the threshold → fires at minimum confidence
"""

from decimal import Decimal

from sqlalchemy import text

from tests.fixtures.rules import AS_OF, setup_detection_fixture
from valeri_api.rules import sleeping_customer


def _orders_every(step: int, count: int, last_days_ago: int, amount: str = "300.00") -> list:
    return [(last_days_ago + step * n, [(1, amount)]) for n in range(count)]


TRUE_POSITIVE = {
    "id": 1,
    "segment": "restoran",
    # 12 orders every 10 days, last one 90 days ago → gap_ratio 9.0, conf capped at 0.95.
    "orders": _orders_every(10, 12, 90),
}

STILL_ACTIVE_MUST_NOT_FIRE = {
    "id": 2,
    "segment": "restoran",
    # Last order 15 days ago with a 10-day cadence → gap_ratio 1.5 < 3.
    "orders": _orders_every(10, 12, 15),
}

SLOW_CADENCE_MUST_NOT_FIRE = {
    "id": 3,
    "segment": "škola",
    # 30-day cadence, last order 70 days ago: 70 ≥ min_gap_days but ratio 2.33 < 3 (GREATEST guard).
    "orders": _orders_every(30, 12, 70),
}

BORDERLINE = {
    "id": 4,
    "segment": "klinika",
    # 20-day cadence, last order 60 days ago → ratio exactly 3.0, gap exactly 60 → conf 0.500.
    "orders": _orders_every(20, 12, 60),
}


def test_true_positive_fires_with_evidence(rule_session) -> None:
    setup_detection_fixture(rule_session, [TRUE_POSITIVE])
    drafts = sleeping_customer.detect(rule_session, AS_OF)

    assert len(drafts) == 1
    draft = drafts[0]
    assert draft.customer_id == 1
    assert draft.evidence["avg_order_interval_d"] == Decimal("10.00")
    assert draft.evidence["gap_days"] == 90
    assert draft.evidence["gap_ratio"] == Decimal("9.00")
    assert draft.evidence["order_count"] == 12
    assert len(draft.evidence["invoices"]) == 3
    # confidence = 0.5 + 0.1 × (9 − 3) = 1.1 → capped at 0.95 → visoka
    assert draft.confidence == Decimal("0.950")
    assert draft.register == "analiza"


def test_active_and_slow_cadence_customers_do_not_fire(rule_session) -> None:
    setup_detection_fixture(rule_session, [STILL_ACTIVE_MUST_NOT_FIRE, SLOW_CADENCE_MUST_NOT_FIRE])
    assert sleeping_customer.detect(rule_session, AS_OF) == []


def test_borderline_minimum_confidence(rule_session) -> None:
    setup_detection_fixture(rule_session, [BORDERLINE])
    drafts = sleeping_customer.detect(rule_session, AS_OF)
    assert len(drafts) == 1
    assert drafts[0].confidence == Decimal("0.500")


def test_inactive_customer_status_guard(rule_session) -> None:
    """A customer already marked inactive/closed is not reported as sleeping."""
    closed = dict(TRUE_POSITIVE, id=5, status="closed")
    setup_detection_fixture(rule_session, [closed])
    assert sleeping_customer.detect(rule_session, AS_OF) == []


def test_threshold_comes_from_rule_config(rule_session) -> None:
    """Raising min_history_orders above the case's count stops the signal."""
    setup_detection_fixture(rule_session, [TRUE_POSITIVE])
    assert len(sleeping_customer.detect(rule_session, AS_OF)) == 1

    rule_session.execute(
        text(
            "UPDATE app.rule_config SET value = '20'::jsonb "
            "WHERE rule = 'sleeping_customer' AND param = 'min_history_orders'"
        )
    )
    assert sleeping_customer.detect(rule_session, AS_OF) == []
