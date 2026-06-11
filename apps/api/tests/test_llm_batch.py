"""P3 Batch API: weekly-cycle narration is batched (~half price) with a live fallback.

FallbackClient is the testable seam — a batch failure degrades to a live call, and
a batched response logs batched=true so the cost ledger applies the discount.
"""

import json
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.llm.batch import FallbackClient
from valeri_api.llm.client import LLMResponse, LLMUnavailable
from valeri_api.llm.router.roles import ROLE_REPORT_NARRATION
from valeri_api.llm.structured import narrate_structured

pytestmark = pytest.mark.usefixtures("db_engine")


class _FakeBatch:
    """A batch client: marks its response batched (so the discount applies)."""

    model = "claude-sonnet-4-6"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    def complete(self, system: str, user: str) -> LLMResponse:
        self.calls += 1
        if self.fail:
            raise LLMUnavailable("batch queue down")
        return LLMResponse(
            text=json.dumps({"text": "Sedmični pregled iz baze.", "register": "analiza"}),
            model=self.model,
            tokens=3000,
            latency_ms=10,
            input_tokens=2000,
            output_tokens=1000,
            batched=True,
        )


class _FakeLive:
    model = "claude-sonnet-4-6"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, system: str, user: str) -> LLMResponse:
        self.calls += 1
        return LLMResponse(
            text=json.dumps({"text": "Sedmični pregled iz baze.", "register": "analiza"}),
            model=self.model,
            tokens=3000,
            latency_ms=20,
            input_tokens=2000,
            output_tokens=1000,
            batched=False,
        )


def _schema():
    from pydantic import BaseModel

    class _Out(BaseModel):
        text: str
        register: str

    return _Out


def _latest_ailog(session: Session):
    return session.execute(
        text("SELECT batched, cost_usd FROM audit.ai_log ORDER BY id DESC LIMIT 1")
    ).one()


def test_batched_response_logged_and_discounted(db_session: Session) -> None:
    client = FallbackClient(_FakeBatch(), _FakeLive())
    narrate_structured(
        db_session,
        masked_payload={"week": "x"},
        schema=_schema(),
        system_prompt="sys",
        instruction="opiši",
        client=client,
        role=ROLE_REPORT_NARRATION,
    )
    db_session.flush()
    row = _latest_ailog(db_session)
    assert row.batched is True
    # Sonnet 3/15 per MTok, batched 0.5: (2000/1e6*3 + 1000/1e6*15) × 0.5 = 0.0105
    assert row.cost_usd == Decimal("0.010500")


def test_batch_failure_falls_back_live(db_session: Session) -> None:
    batch = _FakeBatch(fail=True)
    live = _FakeLive()
    client = FallbackClient(batch, live)
    out, model, _ = narrate_structured(
        db_session,
        masked_payload={"week": "x"},
        schema=_schema(),
        system_prompt="sys",
        instruction="opiši",
        client=client,
        role=ROLE_REPORT_NARRATION,
    )
    db_session.flush()
    assert batch.calls == 1 and live.calls == 1  # tried batch, fell back live
    row = _latest_ailog(db_session)
    assert row.batched is False  # the live call is full price
    assert row.cost_usd == Decimal("0.021000")  # (2000/1e6*3 + 1000/1e6*15)
    assert out.text  # the report still got its narration
