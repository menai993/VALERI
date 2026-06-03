"""CI2 referral_source_risk: a quiet referrer puts its referrals at risk.

A confirmed referral edge whose referrer has gone quiet (gap ≥ threshold) flags
the referred customer, citing the referrer. An active referrer flags nothing.
"""

import datetime

import pytest
from sqlalchemy.orm import Session

from tests.graph_helpers import add_customer, add_edge, add_expectation
from valeri_api.rules import referral_risk

_TODAY = datetime.date.today()


@pytest.mark.anyio
async def test_quiet_referrer_flags_referral(db_session: Session) -> None:
    referrer = add_customer(db_session, "Hotel Preporučitelj")
    referred = add_customer(db_session, "Restoran Preporučeni")
    add_expectation(db_session, referrer, gap_days=70, stretch_ratio=2.3)  # quiet ≥ 60
    add_expectation(db_session, referred, gap_days=10, stretch_ratio=0.6)
    add_edge(db_session, referrer, referred, "referral", status="active")

    drafts = referral_risk.detect(db_session, _TODAY)

    assert len(drafts) == 1
    draft = drafts[0]
    assert draft.customer_id == referred
    assert draft.evidence["referrer_customer_id"] == referrer
    assert draft.evidence["referrer_gap_days"] == 70
    assert draft.register == "preporuka"


@pytest.mark.anyio
async def test_active_referrer_does_not_flag(db_session: Session) -> None:
    referrer = add_customer(db_session, "Hotel Aktivni")
    referred = add_customer(db_session, "Restoran Mirni")
    add_expectation(db_session, referrer, gap_days=12, stretch_ratio=0.5)  # not quiet
    add_expectation(db_session, referred, gap_days=8, stretch_ratio=0.4)
    add_edge(db_session, referrer, referred, "referral", status="active")

    assert referral_risk.detect(db_session, _TODAY) == []


@pytest.mark.anyio
async def test_proposed_referral_ignored(db_session: Session) -> None:
    referrer = add_customer(db_session, "Hotel Prep Prop")
    referred = add_customer(db_session, "Restoran Prep Prop")
    add_expectation(db_session, referrer, gap_days=90, stretch_ratio=3.0)
    add_expectation(db_session, referred, gap_days=10)
    add_edge(db_session, referrer, referred, "referral", status="proposed")

    assert referral_risk.detect(db_session, _TODAY) == []
