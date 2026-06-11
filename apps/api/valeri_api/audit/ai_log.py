"""Append-only writer for audit.ai_log: one row per LLM call.

INSERT only — there is intentionally no update or delete path (principle 7).
Every call is logged, including rejected/failed attempts (full auditability).
P3: each row carries cost attribution (feature/user/tier/token splits) and a
cost_usd computed at write time from app.llm_pricing — never a guessed number.
"""

from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from valeri_api.audit.models import AiLog
from valeri_api.audit.serialization import jsonable
from valeri_api.llm.cost import compute_cost


def log_ai_call(
    session: Session,
    model: str,
    masked_input: dict[str, Any],
    output: dict[str, Any] | None,
    confidence: Decimal | float | None = None,
    register: str | None = None,
    tokens: int | None = None,
    latency_ms: int | None = None,
    *,
    feature: str | None = None,
    user_id: int | None = None,
    tier: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cached_input_tokens: int | None = None,
    batched: bool = False,
) -> AiLog:
    """Append one LLM-call record. masked_input must already be PII-free.

    cost_usd is computed from the token splits × app.llm_pricing (NULL when the
    model is unpriced). `feature` is the M12 router role; `tier` is the routed
    tier. Cost is keyed on `model` (the id/alias the gateway echoed back).
    """
    cost = compute_cost(
        session,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=cached_input_tokens,
        batched=batched,
    )
    entry = AiLog(
        model=model,
        masked_input=jsonable(masked_input),
        output=jsonable(output) if output is not None else None,
        confidence=Decimal(str(confidence)) if confidence is not None else None,
        register=register,
        tokens=tokens,
        latency_ms=latency_ms,
        feature=feature,
        user_id=user_id,
        tier=tier,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached=bool(cached_input_tokens),
        cached_input_tokens=cached_input_tokens,
        batched=batched,
        cost_usd=cost,
    )
    session.add(entry)
    session.flush()
    return entry
