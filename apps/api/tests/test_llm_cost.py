"""P3 cost math (trust-critical, TDD-first): per-call cost = tokens × DB price.

compute_cost is pure Decimal over app.llm_pricing; an unknown model yields NULL
(never a guess). log_ai_call attributes feature/tier/user_id/token splits and
computes cost at write time. These are the principle-1 contract for spend.
"""

from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.audit.ai_log import log_ai_call
from valeri_api.llm.cost import compute_cost

pytestmark = pytest.mark.usefixtures("db_engine")


# ── compute_cost golden cases (Haiku seed: in 1.00 / out 5.00 / cache 0.10 / batch 0.5) ──


def test_cost_formula_plain(db_session: Session) -> None:
    cost = compute_cost(db_session, "claude-haiku-4-5", input_tokens=1000, output_tokens=500)
    # 1000/1e6*1.00 + 500/1e6*5.00 = 0.001 + 0.0025
    assert cost == Decimal("0.003500")


def test_cost_formula_cached_input(db_session: Session) -> None:
    cost = compute_cost(
        db_session,
        "claude-haiku-4-5",
        input_tokens=1000,
        output_tokens=500,
        cached_input_tokens=400,
    )
    # (600/1e6*1.00) + (400/1e6*0.10) + (500/1e6*5.00) = 0.0006 + 0.00004 + 0.0025
    assert cost == Decimal("0.003140")


def test_cost_formula_batched(db_session: Session) -> None:
    cost = compute_cost(
        db_session, "claude-haiku-4-5", input_tokens=1000, output_tokens=500, batched=True
    )
    assert cost == Decimal("0.001750")  # 0.0035 × 0.5


def test_cost_formula_cached_and_batched(db_session: Session) -> None:
    cost = compute_cost(
        db_session,
        "claude-haiku-4-5",
        input_tokens=1000,
        output_tokens=500,
        cached_input_tokens=400,
        batched=True,
    )
    assert cost == Decimal("0.001570")  # 0.00314 × 0.5


def test_tier_alias_is_priced(db_session: Session) -> None:
    """The gateway may echo a tier alias instead of the model id — both are seeded."""
    assert compute_cost(db_session, "tier1", input_tokens=1000, output_tokens=0) == Decimal(
        "0.001000"
    )


def test_unknown_model_costs_none(db_session: Session) -> None:
    assert compute_cost(db_session, "no-such-model", input_tokens=1000, output_tokens=500) is None


# ── log_ai_call attribution + cost at write time ──────────────────────────────


def test_log_ai_call_attributes_and_prices(db_session: Session) -> None:
    entry = log_ai_call(
        db_session,
        model="claude-haiku-4-5",
        masked_input={"k": "v"},
        output={"text": "x"},
        feature="narration",
        user_id=7,
        tier="tier1",
        input_tokens=1000,
        output_tokens=500,
        cached_input_tokens=0,
        batched=False,
    )
    db_session.flush()
    row = db_session.execute(
        text(
            "SELECT feature, user_id, tier, input_tokens, output_tokens, cached, "
            "batched, cost_usd FROM audit.ai_log WHERE id = :id"
        ),
        {"id": entry.id},
    ).one()
    assert row.feature == "narration"
    assert row.user_id == 7
    assert row.tier == "tier1"
    assert row.input_tokens == 1000
    assert row.output_tokens == 500
    assert row.cached is False
    assert row.batched is False
    assert row.cost_usd == Decimal("0.003500")


def test_log_ai_call_unknown_model_null_cost(db_session: Session) -> None:
    entry = log_ai_call(
        db_session,
        model="mystery-model",
        masked_input={},
        output=None,
        feature="intent",
        input_tokens=100,
        output_tokens=10,
    )
    db_session.flush()
    cost = db_session.execute(
        text("SELECT cost_usd FROM audit.ai_log WHERE id = :id"), {"id": entry.id}
    ).scalar_one()
    assert cost is None


def test_cached_flag_set_when_cached_tokens_present(db_session: Session) -> None:
    entry = log_ai_call(
        db_session,
        model="claude-haiku-4-5",
        masked_input={},
        output={"text": "x"},
        feature="simple_qa",
        input_tokens=1000,
        output_tokens=100,
        cached_input_tokens=300,
    )
    db_session.flush()
    cached = db_session.execute(
        text("SELECT cached FROM audit.ai_log WHERE id = :id"), {"id": entry.id}
    ).scalar_one()
    assert cached is True


# ── the chokepoint attributes every call (feature=role, tier, user, token splits) ──


def test_chokepoints_attribute_calls(db_session: Session) -> None:
    """narrate_structured tags its ai_log row with the role, routed tier, the
    acting user, and the gateway's token splits — so cost rolls up by all three."""
    import json

    from pydantic import BaseModel

    from valeri_api.llm.client import LLMResponse
    from valeri_api.llm.router.roles import ROLE_SIMPLE_QA
    from valeri_api.llm.structured import narrate_structured

    class _Out(BaseModel):
        text: str
        register: str
        confidence: float

    class _Fake:
        model = "claude-haiku-4-5"

        def complete(self, system: str, user: str) -> LLMResponse:
            return LLMResponse(
                text=json.dumps(
                    {"text": "Pregled iz baze podataka.", "register": "analiza", "confidence": 0.9}
                ),
                model=self.model,
                tokens=1500,
                latency_ms=40,
                input_tokens=1000,
                output_tokens=500,
            )

    narrate_structured(
        db_session,
        masked_payload={"context": "x"},
        schema=_Out,
        system_prompt="sys",
        instruction="opiši",
        client=_Fake(),
        role=ROLE_SIMPLE_QA,
        user_id=42,
    )
    db_session.flush()
    row = db_session.execute(
        text(
            "SELECT feature, tier, user_id, input_tokens, output_tokens, cost_usd "
            "FROM audit.ai_log ORDER BY id DESC LIMIT 1"
        )
    ).one()
    assert row.feature == ROLE_SIMPLE_QA
    assert row.tier == "tier1"  # simple_qa routes to Haiku
    assert row.user_id == 42
    assert row.input_tokens == 1000
    assert row.output_tokens == 500
    assert row.cost_usd == Decimal("0.003500")
