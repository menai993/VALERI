"""customer_decline rule: labeled cases per docs/rules/customer-decline.md.

Cases (fixtures built via tests/fixtures/rules):
  true_positive            — real decline, no seasonal pattern → fires, srednja
  must_not_fire (seasonal) — same drop but identical last year → does NOT fire
  low_confidence_borderline — ratio just under threshold → fires with niska
  control (healthy)        — stable customer → does NOT fire
"""

from decimal import Decimal

from sqlalchemy import text

from tests.fixtures.rules import AS_OF, setup_detection_fixture
from valeri_api.rules import customer_decline

# ── labeled cases ─────────────────────────────────────────────────────────────

# Baseline window (60..240 days ago): 6 × 500 = 3000 → baseline 1000.00/60d.
_BASELINE_ORDERS = [(days, [(1, "500.00")]) for days in (70, 100, 130, 160, 190, 220)]

TRUE_POSITIVE = {
    "id": 1,
    "segment": "hotel",
    # 60d window: 450 → ratio 0.45; nothing last year → not seasonal.
    # confidence = 0.4 + 0.5*(0.65-0.45)/(0.65-0.35) = 0.733 → srednja
    "orders": [(30, [(1, "450.00")]), *_BASELINE_ORDERS],
}

SEASONAL_MUST_NOT_FIRE = {
    "id": 2,
    "segment": "kafić",
    # Same ratio 0.45 BUT last year's same window totals 460 → yoy 450/460 = 0.978 ≥ 0.75.
    "orders": [
        (30, [(1, "450.00")]),
        *_BASELINE_ORDERS,
        (370, [(1, "100.00")]),
        (390, [(1, "180.00")]),
        (410, [(1, "180.00")]),
    ],
}

LOW_CONFIDENCE_BORDERLINE = {
    "id": 3,
    "segment": "restoran",
    # 60d window: 630 → ratio 0.63 (just under 0.65).
    # confidence = 0.4 + 0.5*(0.65-0.63)/0.30 = 0.433 → niska
    "orders": [(30, [(1, "630.00")]), *_BASELINE_ORDERS],
}

HEALTHY_CONTROL = {
    "id": 4,
    "segment": "hotel",
    # 60d window equals the baseline → ratio 1.0 → no signal.
    "orders": [(30, [(1, "1000.00")]), *_BASELINE_ORDERS],
}

ALL_CASES = [TRUE_POSITIVE, SEASONAL_MUST_NOT_FIRE, LOW_CONFIDENCE_BORDERLINE, HEALTHY_CONTROL]


# ── tests ─────────────────────────────────────────────────────────────────────


def test_cases_fire_and_guard_correctly(rule_session) -> None:
    setup_detection_fixture(rule_session, ALL_CASES)
    drafts = customer_decline.detect(rule_session, AS_OF)
    by_customer = {draft.customer_id: draft for draft in drafts}

    # true positive fires with the hand-computed evidence and confidence
    assert TRUE_POSITIVE["id"] in by_customer, "true positive did not fire"
    draft = by_customer[TRUE_POSITIVE["id"]]
    assert draft.evidence["value"] == Decimal("450.00")
    assert draft.evidence["baseline"] == Decimal("1000.00")
    assert draft.evidence["ratio"] == Decimal("0.450")
    assert draft.confidence == Decimal("0.733")
    assert draft.register == "analiza"
    assert len(draft.evidence["invoices"]) == 1  # the single 60d-window invoice
    assert draft.evidence["period"]["to"] == AS_OF.isoformat()

    # seasonal café must NOT fire (the guard)
    assert SEASONAL_MUST_NOT_FIRE["id"] not in by_customer, "seasonal customer fired"

    # borderline fires with low confidence
    assert LOW_CONFIDENCE_BORDERLINE["id"] in by_customer
    assert by_customer[LOW_CONFIDENCE_BORDERLINE["id"]].confidence == Decimal("0.433")

    # healthy control must not fire
    assert HEALTHY_CONTROL["id"] not in by_customer


def test_confidence_bands(rule_session) -> None:
    from valeri_api.rules.engine import conf_band

    setup_detection_fixture(rule_session, ALL_CASES)
    assert conf_band(rule_session, Decimal("0.733")) == "srednja"
    assert conf_band(rule_session, Decimal("0.433")) == "niska"
    assert conf_band(rule_session, Decimal("0.800")) == "visoka"


def test_threshold_comes_from_rule_config(rule_session) -> None:
    """Tightening decline_ratio_threshold below the case's ratio stops the signal."""
    setup_detection_fixture(rule_session, [TRUE_POSITIVE])
    assert len(customer_decline.detect(rule_session, AS_OF)) == 1

    rule_session.execute(
        text(
            "UPDATE app.rule_config SET value = '0.40'::jsonb "
            "WHERE rule = 'customer_decline' AND param = 'decline_ratio_threshold'"
        )
    )
    assert customer_decline.detect(rule_session, AS_OF) == []


def test_min_baseline_guard(rule_session) -> None:
    """Customers below min_baseline_60d never fire, however deep the drop."""
    tiny = {
        "id": 9,
        "segment": "kafić",
        # baseline = 360/3 = 120 < 500 → guarded out despite ratio 0.25
        "orders": [
            (30, [(1, "30.00")]),
            *[(days, [(1, "60.00")]) for days in (70, 100, 130, 160, 190, 220)],
        ],
    }
    setup_detection_fixture(rule_session, [tiny])
    assert customer_decline.detect(rule_session, AS_OF) == []
