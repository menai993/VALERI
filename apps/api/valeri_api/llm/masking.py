"""PII masking — the load-bearing step before every LLM call (principle 6).

Customer identity → stable salted pseudonym (+ segment). Contact data (names,
e-mails, phones, addresses) is never included at all. Articles, categories,
dates, and SQL-computed numbers pass through. Rehydration (pseudonym → real
name) happens only for human-facing output.
"""

import hashlib
import hmac
import re
from typing import Any

from pydantic import BaseModel

from valeri_api.config import get_settings

# Evidence keys that may carry person-identifying data and are never forwarded.
_FORBIDDEN_KEYS = {"name", "email", "phone", "address", "contact", "kontakt"}


def pseudonym(customer_id: int, salt: str | None = None) -> str:
    """Stable, salted, non-reversible pseudonym for a customer: 'Kupac-xxxxxx'."""
    key = (salt if salt is not None else get_settings().pii_salt).encode()
    digest = hmac.new(key, str(customer_id).encode(), hashlib.sha256).hexdigest()
    return f"Kupac-{digest[:6]}"


class MaskingContext(BaseModel):
    """Pseudonym ↔ real-name mapping for one narration (used only for rehydration)."""

    pseudonyms: dict[str, str] = {}  # pseudonym -> real name
    customer_ids: dict[str, int] = {}  # pseudonym -> customer id (server-side ref resolution)

    def register_customer(self, customer_id: int, real_name: str) -> str:
        alias = pseudonym(customer_id)
        self.pseudonyms[alias] = real_name
        self.customer_ids[alias] = customer_id
        return alias

    def customer_id_for(self, alias: str) -> int | None:
        """Map a pseudonym the model referenced back to the real customer id."""
        return self.customer_ids.get(alias)


def build_masked_payload(
    rule: str,
    evidence: dict[str, Any],
    customer_id: int | None,
    customer_name: str | None,
    segment: str | None,
) -> tuple[dict[str, Any], MaskingContext]:
    """Build the PII-free payload that is allowed to reach a prompt.

    Returns (masked_payload, context). The payload carries the pseudonym and
    segment instead of the customer's identity; evidence passes through after a
    defensive scrub of any person-identifying keys.
    """
    context = MaskingContext()
    alias = None
    if customer_id is not None:
        alias = context.register_customer(customer_id, customer_name or "")

    return (
        {
            "signal": rule,
            "kupac": alias,  # pseudonym, never the real name
            "segment": segment,
            "podaci": _scrub(evidence),
        },
        context,
    )


def _scrub(value: Any) -> Any:
    """Defensively drop any key that could carry person-identifying data."""
    if isinstance(value, dict):
        return {
            key: _scrub(item) for key, item in value.items() if key.lower() not in _FORBIDDEN_KEYS
        }
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    return value


def rehydrate(text: str, context: MaskingContext) -> str:
    """Replace pseudonyms with real names — for human-facing output only."""
    result = text
    for alias, real_name in context.pseudonyms.items():
        if real_name:
            result = result.replace(alias, real_name)
    return result


# ── chat masking (M9): free text + tool outputs ──────────────────────────────


def mask_text(text: str, resolved: list[tuple[str, int, str]], context: MaskingContext) -> str:
    """Replace resolved entity mentions in free text with pseudonyms.

    `resolved` is [(matched_text, customer_id, real_name)] from server-side entity
    resolution (conversation/resolution.py) — the model never resolves entities.
    """
    masked = text
    for matched_text, customer_id, real_name in resolved:
        alias = context.register_customer(customer_id, real_name)
        masked = masked.replace(matched_text, alias)
    return masked


def mask_customer_fields(payload: Any, context: MaskingContext) -> Any:
    """Mask customer identity inside tool outputs before they reach a prompt.

    Wherever a dict carries customer_id + customer_name together, the name is
    replaced by the pseudonym (registered for later rehydration). Contact-style
    keys are scrubbed defensively.
    """
    if isinstance(payload, dict):
        masked = {}
        customer_id = payload.get("customer_id")
        for key, value in payload.items():
            if key.lower() in _FORBIDDEN_KEYS:
                continue
            if key == "customer_name" and customer_id is not None and value:
                masked[key] = context.register_customer(customer_id, str(value))
            else:
                masked[key] = mask_customer_fields(value, context)
        return masked
    if isinstance(payload, list):
        return [mask_customer_fields(item, context) for item in payload]
    return payload


# ── allowed-number collection (for the number contract) ──────────────────────

_NUMBER_PATTERN = re.compile(r"-?\d+(?:[.,]\d+)?")


def collect_allowed_numbers(payload: Any) -> set[str]:
    """Every numeric token present in the masked payload, in normalised form.

    The narration may only ever contain these numbers (plus their absolute
    values — the model may phrase '-55.3' as a 'pad od 55.3%').
    """
    allowed: set[str] = set()
    _walk(payload, allowed)
    return allowed


def _walk(value: Any, allowed: set[str]) -> None:
    if isinstance(value, dict):
        for item in value.values():
            _walk(item, allowed)
    elif isinstance(value, list):
        for item in value:
            _walk(item, allowed)
    elif isinstance(value, bool):
        return
    elif isinstance(value, int | float):
        allowed.update(_normalise(str(value)))
    elif isinstance(value, str):
        for token in _NUMBER_PATTERN.findall(value):
            allowed.update(_normalise(token))


def _normalise(token: str) -> set[str]:
    """Normalised variants of one numeric token (sign-less, comma/dot, trailing zeros)."""
    cleaned = token.replace(",", ".").lstrip("-")
    variants = {cleaned}
    if "." in cleaned:
        variants.add(cleaned.rstrip("0").rstrip("."))  # 55.30 -> 55.3
        integer_part, _, fraction = cleaned.partition(".")
        variants.add(integer_part)  # the integer part alone is also acceptable
    return variants
