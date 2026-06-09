"""CI2 group_risk: confirmed owner/group/chain objects declining TOGETHER.

A confirmed same_owner group with one sharply declining object fires ONE
group-level signal (members + combined SQL numbers); a proposed edge or a healthy
group fires nothing. Numbers from SQL.
"""

import datetime

import pytest
from sqlalchemy.orm import Session

from tests.graph_helpers import add_customer, add_edge, add_metrics
from valeri_api.rules import group_risk

_TODAY = datetime.date.today()


@pytest.mark.anyio
async def test_confirmed_same_owner_group_fires_together(db_session: Session) -> None:
    a = add_customer(db_session, "Hotel Grupa A")
    b = add_customer(db_session, "Hotel Grupa B")
    add_metrics(db_session, a, turnover_60d=1000, baseline_60d=5000)  # sharply declining
    add_metrics(db_session, b, turnover_60d=4000, baseline_60d=4000)  # stable
    add_edge(db_session, a, b, "same_owner", status="active")

    drafts = group_risk.detect(db_session, _TODAY)

    assert len(drafts) == 1
    draft = drafts[0]
    assert set(draft.evidence["members"]) == {a, b}  # both objects, together
    assert draft.customer_id == a  # anchored on the worst-ratio member
    # Combined turnover 5000 / baseline 9000 = 0.556 < 0.7.
    assert float(draft.evidence["group_turnover_60d"]) == 5000.0
    assert float(draft.evidence["group_baseline_60d"]) == 9000.0
    assert abs(float(draft.evidence["ratio"]) - 0.556) < 0.001
    assert draft.register == "preporuka"


@pytest.mark.anyio
async def test_proposed_edge_does_not_trigger(db_session: Session) -> None:
    a = add_customer(db_session, "Hotel Prop A")
    b = add_customer(db_session, "Hotel Prop B")
    add_metrics(db_session, a, turnover_60d=1000, baseline_60d=5000)
    add_metrics(db_session, b, turnover_60d=4000, baseline_60d=4000)
    add_edge(db_session, a, b, "same_owner", status="proposed")  # NOT confirmed

    assert group_risk.detect(db_session, _TODAY) == []  # confirmed edges only


@pytest.mark.anyio
async def test_healthy_group_does_not_fire(db_session: Session) -> None:
    a = add_customer(db_session, "Hotel Zdrav A")
    b = add_customer(db_session, "Hotel Zdrav B")
    add_metrics(db_session, a, turnover_60d=4500, baseline_60d=5000)
    add_metrics(db_session, b, turnover_60d=4000, baseline_60d=4000)
    add_edge(db_session, a, b, "same_owner", status="active")

    # Combined 8500 / 9000 = 0.944 ≥ 0.7 → no group risk.
    assert group_risk.detect(db_session, _TODAY) == []


@pytest.mark.anyio
async def test_single_object_below_min_members_does_not_fire(db_session: Session) -> None:
    """A lone declining object with no confirmed group is not a group signal."""
    a = add_customer(db_session, "Hotel Sam")
    add_metrics(db_session, a, turnover_60d=500, baseline_60d=5000)
    assert group_risk.detect(db_session, _TODAY) == []
