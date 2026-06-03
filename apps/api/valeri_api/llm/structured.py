"""Generic structured narration: the reusable core of the M6 LLM discipline.

mask → route (M12) → prompt → call → schema-validate → number contract → audit log
→ retry → cascade.

narrate_task (M6) is the task-specific entry point; this generic version backs
report sections, customer-message drafts (M7), chat (M9), rule proposals (M10) and
audit summaries (M11). Every API call — including rejected attempts — writes one
audit.ai_log row; every routing decision writes one audit.llm_route_log row.

Cascade (M12): a valid output whose self-confidence is below the configured
threshold, or a retry budget exhausted by validator rejects, escalates ONE tier up
(when cascade is enabled). The escalated tier gets a fresh retry budget; if it also
fails, a valid low-confidence original is still better than nothing.
"""

import logging
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from valeri_api.audit.ai_log import log_ai_call
from valeri_api.audit.serialization import jsonable
from valeri_api.config import get_settings

# get_llm_client stays imported here: it is the seam tests monkeypatch to keep
# production code paths off the network (the router honours patched factories).
from valeri_api.llm.client import LLMClient, LLMResponse, LLMUnavailable, get_llm_client
from valeri_api.llm.masking import collect_allowed_numbers
from valeri_api.llm.prompts import structured_prompt
from valeri_api.llm.router.roles import ROLE_NARRATION
from valeri_api.llm.router.router import (
    REASON_LOW_CONFIDENCE,
    REASON_VALIDATOR_REJECT,
    client_for_route,
    escalate,
    initial_route,
    load_router_config,
)
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
    text_field: str | None = "text",
    role: str = ROLE_NARRATION,
) -> tuple[T, str, int]:
    """Produce a validated structured output for an already-masked payload.

    Returns (validated_output, model, attempts). Raises NarrationFailed when the
    gateway is unavailable or output cannot be validated within the (possibly
    cascaded) retry budget — never returns unvalidated output.

    The number contract (principle 1) is checked on `text_field`; pass None for
    outputs with no narrative text (e.g. intent classification — it produces no
    user-facing numbers). `register` is written to ai_log when the schema itself
    carries no register field. `role` (M12) decides which tier answers; an
    injected `client` is always honoured but the routing decision is still logged.
    """
    settings = get_settings()
    max_attempts = settings.llm_max_retries + 1

    # Exact string forms for Decimals/dates: what the prompt shows, the log
    # stores, and the allowed-number set is built from.
    masked_payload = jsonable(masked_payload)
    allowed_numbers = collect_allowed_numbers(masked_payload)

    # ── routing (M12): the role picks the tier; masking already happened upstream ──
    router_config = load_router_config(session)
    route = initial_route(session, role, override=client)
    llm_client = client_for_route(route, override=client, factory=lambda: get_llm_client())

    # A valid-but-low-confidence result, kept as fallback if escalation yields nothing better.
    fallback: tuple[T, LLMResponse, int] | None = None

    errors: list[str] = []
    while True:  # tier loop: the initial tier + at most cascade_max_escalations
        escalated_mid_loop = False

        for attempt in range(1, max_attempts + 1):
            user_prompt = structured_prompt(instruction, masked_payload, errors)

            # ── the API call ──────────────────────────────────────────────────
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

            # ── schema validation ────────────────────────────────────────────
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
                logger.warning(
                    "structured output rejected (schema), attempt %d: %s", attempt, errors
                )
                continue

            # ── the number contract (principle 1) ────────────────────────────
            violations = (
                check_number_contract(getattr(parsed, text_field), allowed_numbers)
                if text_field is not None
                else []
            )
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

            # ── valid output: low-self-confidence cascade (M12) ──────────────
            confidence = getattr(parsed, "confidence", None)
            if (
                confidence is not None
                and float(confidence) < router_config["escalation_confidence_threshold"]
            ):
                escalated = escalate(
                    session,
                    route,
                    REASON_LOW_CONFIDENCE,
                    confidence=float(confidence),
                    override=client,
                )
                if escalated is not None:
                    fallback = (parsed, response, attempt)
                    route = escalated
                    llm_client = client_for_route(
                        route, override=client, factory=lambda: get_llm_client()
                    )
                    errors = []
                    escalated_mid_loop = True
                    break  # → tier loop: retry on the stronger tier

            # ── accepted ─────────────────────────────────────────────────────
            log_ai_call(
                session,
                model=response.model,
                masked_input=masked_payload,
                output=parsed.model_dump(),
                confidence=confidence,
                register=getattr(parsed, "register", None) or register,
                tokens=response.tokens,
                latency_ms=response.latency_ms,
            )
            return parsed, response.model, attempt

        if escalated_mid_loop:
            continue  # run the retry loop on the escalated tier

        # ── retry budget exhausted by validator rejects → cascade or fail ────
        escalated = escalate(session, route, REASON_VALIDATOR_REJECT, override=client)
        if escalated is not None:
            route = escalated
            llm_client = client_for_route(route, override=client, factory=lambda: get_llm_client())
            errors = []
            continue

        # No escalation left: a valid low-confidence original still beats failing.
        if fallback is not None:
            parsed, response, attempt = fallback
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
