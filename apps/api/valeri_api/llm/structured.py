"""Generic structured narration: the reusable core of the M6 LLM discipline.

mask → prompt → call → schema-validate → number contract → audit log → retry.

narrate_task (M6) is the task-specific entry point; this generic version backs
report sections and customer-message drafts (M7) and future structured outputs.
Every API call — including rejected attempts — writes one audit.ai_log row.
"""

import logging
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from valeri_api.audit.ai_log import log_ai_call
from valeri_api.audit.serialization import jsonable
from valeri_api.config import get_settings
from valeri_api.llm.client import LLMClient, LLMUnavailable, get_llm_client
from valeri_api.llm.masking import collect_allowed_numbers
from valeri_api.llm.prompts import structured_prompt
from valeri_api.llm.schemas import NarrationFailed
from valeri_api.llm.validators import NarrationInvalid, check_number_contract, parse_structured

logger = logging.getLogger("valeri.llm.structured")


def narrate_structured[T: BaseModel](
    session: Session,
    masked_payload: dict[str, Any],
    schema: type[T],
    system_prompt: str,
    instruction: str,
    client: LLMClient | None = None,
    register: str | None = None,
    text_field: str = "text",
) -> tuple[T, str, int]:
    """Produce a validated structured output for an already-masked payload.

    Returns (validated_output, model, attempts). Raises NarrationFailed when the
    gateway is unavailable or output cannot be validated within the retry budget
    — never returns unvalidated output.

    The number contract (principle 1) is checked on `text_field`. `register` is
    written to ai_log when the schema itself carries no register field.
    """
    settings = get_settings()
    llm_client = client if client is not None else get_llm_client()
    max_attempts = settings.llm_max_retries + 1

    # Exact string forms for Decimals/dates: what the prompt shows, the log
    # stores, and the allowed-number set is built from.
    masked_payload = jsonable(masked_payload)
    allowed_numbers = collect_allowed_numbers(masked_payload)

    errors: list[str] = []
    for attempt in range(1, max_attempts + 1):
        user_prompt = structured_prompt(instruction, masked_payload, errors)

        # ── the API call ──────────────────────────────────────────────────────
        try:
            response = llm_client.complete(system_prompt, user_prompt)
        except LLMUnavailable as error:
            log_ai_call(
                session,
                model=getattr(llm_client, "model", "unknown"),
                masked_input=masked_payload,
                output={"error": "gateway_unavailable", "detail": str(error)},
            )
            raise NarrationFailed(f"LLM gateway unavailable: {error}", attempt) from error

        # ── schema validation ────────────────────────────────────────────────
        try:
            parsed = parse_structured(response.text, schema)
        except NarrationInvalid as invalid:
            errors = invalid.errors
            log_ai_call(
                session,
                model=response.model,
                masked_input=masked_payload,
                output={"rejected": response.text, "errors": errors},
                tokens=response.tokens,
                latency_ms=response.latency_ms,
            )
            logger.warning("structured output rejected (schema), attempt %d: %s", attempt, errors)
            continue

        # ── the number contract (principle 1) ────────────────────────────────
        violations = check_number_contract(getattr(parsed, text_field), allowed_numbers)
        if violations:
            errors = [
                "Korišteni su brojevi koji NISU u datim podacima: "
                + ", ".join(violations)
                + ". Smiješ koristiti isključivo date brojeve, doslovno."
            ]
            log_ai_call(
                session,
                model=response.model,
                masked_input=masked_payload,
                output={
                    "rejected": parsed.model_dump(),
                    "errors": errors,
                    "number_violations": violations,
                },
                tokens=response.tokens,
                latency_ms=response.latency_ms,
            )
            logger.warning(
                "structured output rejected (numbers), attempt %d: %s", attempt, violations
            )
            continue

        # ── accepted ─────────────────────────────────────────────────────────
        log_ai_call(
            session,
            model=response.model,
            masked_input=masked_payload,
            output=parsed.model_dump(),
            confidence=getattr(parsed, "confidence", None),
            register=getattr(parsed, "register", None) or register,
            tokens=response.tokens,
            latency_ms=response.latency_ms,
        )
        return parsed, response.model, attempt

    raise NarrationFailed(
        f"Structured output rejected after {max_attempts} attempts: {'; '.join(errors)}",
        max_attempts,
    )
