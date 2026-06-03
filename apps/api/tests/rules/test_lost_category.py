"""lost_category rule: labeled cases per docs/rules/lost-category.md.

Cases:
  true_positive             — whole category quiet 100 days, customer still active → fires
  must_not_fire (sleeping)  — customer stopped entirely → does NOT fire
  low_confidence_borderline — gap exactly at gap_days → fires at minimum confidence
"""

from decimal import Decimal

from sqlalchemy import text

from tests.fixtures.rules import AS_OF, setup_detection_fixture
from valeri_api.rules import lost_category

# Category 2 = articles 4-6. Six distinct purchase dates, last one 100 days ago.
_CATEGORY_PATTERN = [(days, [(4, "120.00")]) for days in (200, 180, 160, 140, 120, 100)]
_STILL_ACTIVE = [(days, [(1, "80.00")]) for days in (80, 60, 40, 20)]

TRUE_POSITIVE = {"id": 1, "segment": "hotel", "orders": [*_CATEGORY_PATTERN, *_STILL_ACTIVE]}

SLEEPING_MUST_NOT_FIRE = {"id": 2, "segment": "restoran", "orders": list(_CATEGORY_PATTERN)}

BORDERLINE = {
    "id": 3,
    "segment": "klinika",
    # Last category purchase exactly 90 days ago → conf 0.500.
    "orders": [
        *[(days, [(4, "120.00")]) for days in (190, 170, 150, 130, 110, 90)],
        *[(days, [(1, "80.00")]) for days in (50, 20)],
    ],
}


def test_true_positive_fires_with_evidence(rule_session) -> None:
    setup_detection_fixture(rule_session, [TRUE_POSITIVE])
    drafts = lost_category.detect(rule_session, AS_OF)

    # Only category 2 is lost (category 1 purchases are recent).
    assert len(drafts) == 1
    draft = drafts[0]
    assert draft.customer_id == 1
    assert draft.article_id is None
    assert draft.evidence["category_id"] == 2
    assert draft.evidence["category_name"] == "hemija"
    assert draft.evidence["gap_days"] == 100
    assert draft.evidence["purchases_before"] == 6
    # confidence = 0.5 + 0.1 × (100 − 90)/30 = 0.533
    assert draft.confidence == Decimal("0.533")
    assert draft.register == "analiza"


def test_sleeping_customer_does_not_fire(rule_session) -> None:
    setup_detection_fixture(rule_session, [SLEEPING_MUST_NOT_FIRE])
    assert lost_category.detect(rule_session, AS_OF) == []


def test_borderline_minimum_confidence(rule_session) -> None:
    setup_detection_fixture(rule_session, [BORDERLINE])
    drafts = lost_category.detect(rule_session, AS_OF)
    assert len(drafts) == 1
    assert drafts[0].confidence == Decimal("0.500")


def test_threshold_comes_from_rule_config(rule_session) -> None:
    """Raising gap_days above the case's gap stops the signal."""
    setup_detection_fixture(rule_session, [TRUE_POSITIVE])
    assert len(lost_category.detect(rule_session, AS_OF)) == 1

    rule_session.execute(
        text(
            "UPDATE app.rule_config SET value = '150'::jsonb "
            "WHERE rule = 'lost_category' AND param = 'gap_days'"
        )
    )
    assert lost_category.detect(rule_session, AS_OF) == []
