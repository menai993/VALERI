"""lost_article rule: labeled cases per docs/rules/lost-article.md.

Cases:
  true_positive             — regular article goes quiet, customer still active → fires
  must_not_fire (code-swap) — same pattern but the code was swapped → does NOT fire
  must_not_fire (sleeping)  — customer stopped entirely → does NOT fire (sleeping territory)
  low_confidence_borderline — gap exactly at gap_factor × cadence → fires at minimum confidence
"""

from decimal import Decimal

from sqlalchemy import text

from tests.fixtures.rules import AS_OF, setup_detection_fixture
from valeri_api.rules import lost_article

# Article 2 bought every 10 days (days 100..50), then silence; article 1 keeps the
# customer active afterwards.
_LOST_PATTERN = [(days, [(2, "100.00")]) for days in (100, 90, 80, 70, 60, 50)]
_STILL_ACTIVE = [(days, [(1, "80.00")]) for days in (40, 30, 20, 10)]

TRUE_POSITIVE = {"id": 1, "segment": "hotel", "orders": [*_LOST_PATTERN, *_STILL_ACTIVE]}

CODE_SWAP_MUST_NOT_FIRE = {"id": 2, "segment": "hotel", "orders": [*_LOST_PATTERN, *_STILL_ACTIVE]}

SLEEPING_MUST_NOT_FIRE = {"id": 3, "segment": "restoran", "orders": list(_LOST_PATTERN)}

BORDERLINE = {
    "id": 4,
    "segment": "klinika",
    # Article 2 every 10 days (days 60..30), gap exactly 30 = 3.0 × cadence → conf 0.500.
    "orders": [
        *[(days, [(2, "100.00")]) for days in (60, 50, 40, 30)],
        *[(days, [(1, "80.00")]) for days in (20, 10)],
    ],
}


def test_true_positive_fires_with_evidence(rule_session) -> None:
    setup_detection_fixture(rule_session, [TRUE_POSITIVE])
    drafts = lost_article.detect(rule_session, AS_OF)

    assert len(drafts) == 1
    draft = drafts[0]
    assert draft.customer_id == 1
    assert draft.article_id == 2
    assert draft.evidence["avg_interval_d"] == Decimal("10.00")
    assert draft.evidence["gap_days"] == 50
    assert draft.evidence["gap_ratio"] == Decimal("5.00")
    assert draft.evidence["purchases_before_loss"] == 6
    assert draft.evidence["code_swap_check"] == {"is_swapped": False}
    assert len(draft.evidence["invoices_since"]) > 0
    # confidence = 0.5 + 0.1 × (5 − 3) = 0.7
    assert draft.confidence == Decimal("0.700")
    assert draft.register == "analiza"


def test_code_swapped_article_does_not_fire(rule_session) -> None:
    """The code-swap guard: an aliased (retired) code is not a lost article."""
    setup_detection_fixture(
        rule_session,
        [CODE_SWAP_MUST_NOT_FIRE],
        aliases=[{"old_code": "RT-002", "new_article_id": 3}],
    )
    assert lost_article.detect(rule_session, AS_OF) == []


def test_sleeping_customer_article_does_not_fire(rule_session) -> None:
    """No invoices after the article's last purchase → sleeping customer, not lost article."""
    setup_detection_fixture(rule_session, [SLEEPING_MUST_NOT_FIRE])
    assert lost_article.detect(rule_session, AS_OF) == []


def test_borderline_minimum_confidence(rule_session) -> None:
    setup_detection_fixture(rule_session, [BORDERLINE])
    drafts = lost_article.detect(rule_session, AS_OF)
    assert len(drafts) == 1
    assert drafts[0].confidence == Decimal("0.500")


def test_threshold_comes_from_rule_config(rule_session) -> None:
    """Raising gap_factor above the case's gap ratio stops the signal."""
    setup_detection_fixture(rule_session, [TRUE_POSITIVE])
    assert len(lost_article.detect(rule_session, AS_OF)) == 1

    rule_session.execute(
        text(
            "UPDATE app.rule_config SET value = '6.0'::jsonb "
            "WHERE rule = 'lost_article' AND param = 'gap_factor'"
        )
    )
    assert lost_article.detect(rule_session, AS_OF) == []
