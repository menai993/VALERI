"""narrow_basket rule: labeled cases per docs/rules/narrow-basket.md.

Cases:
  true_positive             — 1-category customer among 3-category peers → fires (preporuka)
  must_not_fire (too small) — narrow but below min_baseline_60d → does NOT fire
  low_confidence_borderline — missing categories at exactly min_peer_prevalence → srednja
"""

from decimal import Decimal

from sqlalchemy import text

from tests.fixtures.rules import AS_OF, setup_detection_fixture
from valeri_api.rules import narrow_basket

# Orders that give a baseline of 1000/60d (6 × 500 in the baseline window) + recent activity.
_GOOD_VOLUME = lambda article: [  # noqa: E731
    *[(days, [(article, "500.00")]) for days in (70, 100, 130, 160, 190, 220)],
    (20, [(article, "500.00")]),
]

# Peers buying all three categories (articles 1, 4, 7).
_BROAD_PEER_ORDERS = [
    *[
        (days, [(1, "300.00"), (4, "300.00"), (7, "300.00")])
        for days in (20, 50, 80, 110, 140, 170, 200)
    ],
]


def test_true_positive_fires_as_recommendation(rule_session) -> None:
    """A papir-only klinika among peers who all buy 3 categories → cross-sell signal."""
    scenario = [
        {"id": 1, "segment": "klinika", "orders": _GOOD_VOLUME(1)},  # narrow: papir only
        {"id": 2, "segment": "klinika", "orders": list(_BROAD_PEER_ORDERS)},
        {"id": 3, "segment": "klinika", "orders": list(_BROAD_PEER_ORDERS)},
        {"id": 4, "segment": "klinika", "orders": list(_BROAD_PEER_ORDERS)},
    ]
    setup_detection_fixture(rule_session, scenario)
    drafts = narrow_basket.detect(rule_session, AS_OF)
    by_customer = {draft.customer_id: draft for draft in drafts}

    assert 1 in by_customer, "narrow customer did not fire"
    draft = by_customer[1]
    assert draft.register == "preporuka"
    assert draft.evidence["n_categories"] == 1
    assert draft.evidence["segment"] == "klinika"
    # Missing: hemija + dispenzeri, each bought by 3 of 4 klinika buyers → prevalence 0.75.
    missing_names = {category["name"] for category in draft.evidence["missing_categories"]}
    assert missing_names == {"hemija", "dispenzeri"}
    # confidence = avg(0.75, 0.75) = 0.75 → visoka
    assert draft.confidence == Decimal("0.750")

    # The broad peers must not fire (3 categories > max 2).
    assert 2 not in by_customer and 3 not in by_customer and 4 not in by_customer


def test_small_customer_does_not_fire(rule_session) -> None:
    """Narrow but below min_baseline_60d → not worth a recommendation."""
    scenario = [
        {
            "id": 1,
            "segment": "klinika",
            # baseline = 150/3 = 50 < 300
            "orders": [(days, [(1, "50.00")]) for days in (100, 150, 200)],
        },
        {"id": 2, "segment": "klinika", "orders": list(_BROAD_PEER_ORDERS)},
        {"id": 3, "segment": "klinika", "orders": list(_BROAD_PEER_ORDERS)},
    ]
    setup_detection_fixture(rule_session, scenario)
    drafts = narrow_basket.detect(rule_session, AS_OF)
    assert all(draft.customer_id != 1 for draft in drafts)


def test_borderline_prevalence(rule_session) -> None:
    """Missing categories at exactly min_peer_prevalence (0.6) → srednja confidence."""
    # 5 klinika buyers: C1 narrow (papir); C2, C3 buy all three; C4 papir+hemija;
    # C5 papir+dispenzeri.
    # Prevalence: papir 5/5, hemija 3/5 = 0.6, dispenzeri 3/5 = 0.6.
    scenario = [
        {"id": 1, "segment": "klinika", "orders": _GOOD_VOLUME(1)},
        {"id": 2, "segment": "klinika", "orders": list(_BROAD_PEER_ORDERS)},
        {"id": 3, "segment": "klinika", "orders": list(_BROAD_PEER_ORDERS)},
        {
            "id": 4,
            "segment": "klinika",
            "orders": [(days, [(1, "200.00"), (4, "200.00")]) for days in (30, 90, 150)],
        },
        {
            "id": 5,
            "segment": "klinika",
            "orders": [(days, [(1, "200.00"), (7, "200.00")]) for days in (30, 90, 150)],
        },
    ]
    setup_detection_fixture(rule_session, scenario)
    drafts = narrow_basket.detect(rule_session, AS_OF)
    by_customer = {draft.customer_id: draft for draft in drafts}

    assert 1 in by_customer
    # C1 missing hemija (0.6) + dispenzeri (0.6) → confidence 0.600 → srednja
    assert by_customer[1].confidence == Decimal("0.600")


def test_threshold_comes_from_rule_config(rule_session) -> None:
    """Raising min_peer_prevalence above the peers' share stops the recommendation."""
    scenario = [
        {"id": 1, "segment": "klinika", "orders": _GOOD_VOLUME(1)},
        {"id": 2, "segment": "klinika", "orders": list(_BROAD_PEER_ORDERS)},
        {"id": 3, "segment": "klinika", "orders": list(_BROAD_PEER_ORDERS)},
        {"id": 4, "segment": "klinika", "orders": list(_BROAD_PEER_ORDERS)},
    ]
    setup_detection_fixture(rule_session, scenario)
    assert any(d.customer_id == 1 for d in narrow_basket.detect(rule_session, AS_OF))

    rule_session.execute(
        text(
            "UPDATE app.rule_config SET value = '0.9'::jsonb "
            "WHERE rule = 'narrow_basket' AND param = 'min_peer_prevalence'"
        )
    )
    assert all(d.customer_id != 1 for d in narrow_basket.detect(rule_session, AS_OF))
