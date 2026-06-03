"""Narration orchestration: mask → route → prompt → call → validate → retry → log.

Every LLM API call (including rejected attempts) writes one audit.ai_log row;
every routing decision writes one audit.llm_route_log row (M12). A narration that
fails schema validation or the number contract after the (possibly cascaded) retry
budget raises NarrationFailed — the caller falls back to templates.
"""

import logging
from typing import Any

from sqlalchemy.orm import Session

from valeri_api.audit.ai_log import log_ai_call
from valeri_api.config import get_settings

# get_llm_client stays imported here: it is the seam tests monkeypatch to keep
# production code paths off the network (the router honours patched factories).
from valeri_api.llm.client import LLMClient, LLMResponse, LLMUnavailable, get_llm_client
from valeri_api.llm.masking import build_masked_payload, collect_allowed_numbers
from valeri_api.llm.prompts import SYSTEM_PROMPT, narration_prompt, retry_feedback_prompt
from valeri_api.llm.router.roles import ROLE_NARRATION
from valeri_api.llm.router.router import (
    REASON_LOW_CONFIDENCE,
    REASON_VALIDATOR_REJECT,
    client_for_route,
    escalate,
    initial_route,
    load_router_config,
)
from valeri_api.llm.schemas import NarrationFailed, NarrationResult, TaskNarration
from valeri_api.llm.validators import NarrationInvalid, check_number_contract, parse_narration

logger = logging.getLogger("valeri.llm.narration")


def narrate_task(
    session: Session,
    rule: str,
    evidence: dict[str, Any],
    customer_id: int | None,
    customer_name: str | None,
    segment: str | None,
    client: LLMClient | None = None,
    role: str = ROLE_NARRATION,
) -> NarrationResult:
    """Produce a validated Bosnian narration for one signal.

    Raises NarrationFailed when the gateway is unavailable or the output cannot
    be validated within the (possibly cascaded) retry budget. Never returns
    unvalidated output.
    """
    settings = get_settings()
    max_attempts = settings.llm_max_retries + 1

    masked_payload, context = build_masked_payload(
        rule=rule,
        evidence=evidence,
        customer_id=customer_id,
        customer_name=customer_name,
        segment=segment,
    )
    allowed_numbers = collect_allowed_numbers(masked_payload)

    # ── routing (M12): masking already happened above; the router only picks the client ──
    router_config = load_router_config(session)
    route = initial_route(session, role, override=client)
    llm_client = client_for_route(route, override=client, factory=lambda: get_llm_client())

    # A valid-but-low-confidence narration kept as fallback if escalation yields nothing better.
    fallback: tuple[TaskNarration, LLMResponse, int] | None = None

    errors: list[str] = []
    while True:  # tier loop: the initial tier + at most cascade_max_escalations
        escalated_mid_loop = False

        for attempt in range(1, max_attempts + 1):
            user_prompt = (
                narration_prompt(masked_payload)
                if not errors
                else retry_feedback_prompt(masked_payload, errors)
            )

            # ── the API call ──────────────────────────────────────────────────
            try:
                response = llm_client.complete(SYSTEM_PROMPT, user_prompt)
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
                narration = parse_narration(response.text)
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
                logger.warning("narration rejected (schema), attempt %d: %s", attempt, errors)
                continue

            # ── the number contract (principle 1) ────────────────────────────
            violations = check_number_contract(narration.body, allowed_numbers)
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
                        "rejected": narration.model_dump(),
                        "errors": errors,
                        "number_violations": violations,
                    },
                    tokens=response.tokens,
                    latency_ms=response.latency_ms,
                )
                logger.warning("narration rejected (numbers), attempt %d: %s", attempt, violations)
                continue

            # ── valid output: low-self-confidence cascade (M12) ──────────────
            if narration.confidence < router_config["escalation_confidence_threshold"]:
                escalated = escalate(
                    session,
                    route,
                    REASON_LOW_CONFIDENCE,
                    confidence=narration.confidence,
                    override=client,
                )
                if escalated is not None:
                    fallback = (narration, response, attempt)
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
                output=narration.model_dump(),
                confidence=narration.confidence,
                register=narration.register,
                tokens=response.tokens,
                latency_ms=response.latency_ms,
            )
            return NarrationResult(
                narration=narration, model=response.model, attempts=attempt, context=context
            )

        if escalated_mid_loop:
            continue  # run the retry loop on the escalated tier

        # ── retry budget exhausted by validator rejects → cascade or fail ────
        escalated = escalate(session, route, REASON_VALIDATOR_REJECT, override=client)
        if escalated is not None:
            route = escalated
            llm_client = client_for_route(route, override=client, factory=lambda: get_llm_client())
            errors = []
            continue

        # No escalation left: a valid low-confidence narration still beats failing.
        if fallback is not None:
            narration, response, attempt = fallback
            log_ai_call(
                session,
                model=response.model,
                masked_input=masked_payload,
                output=narration.model_dump(),
                confidence=narration.confidence,
                register=narration.register,
                tokens=response.tokens,
                latency_ms=response.latency_ms,
            )
            return NarrationResult(
                narration=narration, model=response.model, attempts=attempt, context=context
            )

        raise NarrationFailed(
            f"Narration rejected after {max_attempts} attempts: {'; '.join(errors)}", max_attempts
        )
