"""CI2 behavioral_twin_warning: a twin of a churned client showing the same signs.

A confirmed behavioral_twin edge where one twin has declined (early_decline) and
the other is stretching its interval ≥ threshold fires an early warning for the
at-risk twin, citing the churned one. A healthy twin stays quiet.
"""

import datetime

import pytest
from sqlalchemy.orm import Session

from tests.graph_helpers import add_customer, add_edge, add_expectation
from valeri_api.rules import behavioral_twin

_TODAY = datetime.date.today()


@pytest.mark.anyio
async def test_twin_early_warning_fires(db_session: Session) -> None:
    churned = add_customer(db_session, "Kafić Pao")
    at_risk = add_customer(db_session, "Kafić Blizanac")
    add_expectation(db_session, churned, early_decline=True, stretch_ratio=2.0, gap_days=40)
    add_expectation(db_session, at_risk, early_decline=False, stretch_ratio=1.6, gap_days=24)
    add_edge(db_session, churned, at_risk, "behavioral_twin", status="active")

    drafts = behavioral_twin.detect(db_session, _TODAY)

    assert len(drafts) == 1
    draft = drafts[0]
    assert draft.customer_id == at_risk  # warning is for the still-saveable twin
    assert draft.evidence["twin_customer_id"] == churned  # citing the churned one
    assert float(draft.evidence["stretch_ratio"]) == 1.6
    assert draft.register == "preporuka"


@pytest.mark.anyio
async def test_twin_without_signs_does_not_fire(db_session: Session) -> None:
    churned = add_customer(db_session, "Kafić Pao 2")
    healthy = add_customer(db_session, "Kafić Zdrav")
    add_expectation(db_session, churned, early_decline=True, stretch_ratio=2.0, gap_days=40)
    add_expectation(db_session, healthy, early_decline=False, stretch_ratio=1.0, gap_days=10)
    add_edge(db_session, churned, healthy, "behavioral_twin", status="active")

    # The healthy twin's stretch (1.0) is below the 1.5 threshold → no warning.
    assert behavioral_twin.detect(db_session, _TODAY) == []


@pytest.mark.anyio
async def test_proposed_twin_edge_ignored(db_session: Session) -> None:
    churned = add_customer(db_session, "Kafić Pao 3")
    at_risk = add_customer(db_session, "Kafić Blizanac 3")
    add_expectation(db_session, churned, early_decline=True, stretch_ratio=2.0)
    add_expectation(db_session, at_risk, early_decline=False, stretch_ratio=1.7)
    add_edge(db_session, churned, at_risk, "behavioral_twin", status="proposed")

    assert behavioral_twin.detect(db_session, _TODAY) == []
