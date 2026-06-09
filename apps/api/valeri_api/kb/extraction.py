"""Structured knowledge extraction (CI1): masked utterance → typed candidates.

Tier-1, structured output via narrate_structured (schema-validate + reject+retry +
audit.ai_log on every attempt). The model sees ONLY masked text (pseudonyms for
known customers; contact PII stripped) and emits qualitative candidates — never an
entity id, never a computed number. Each pass is logged to app.kb_extraction for
provenance/debug (raw_text is the real utterance, kept on-prem only).
"""

import logging
from typing import Any

from sqlalchemy.orm import Session

from valeri_api.audit.serialization import jsonable
from valeri_api.kb.models import KBExtraction
from valeri_api.kb.prompts import EXTRACTION_INSTRUCTION, EXTRACTION_SYSTEM_PROMPT
from valeri_api.kb.schemas import ExtractionResult
from valeri_api.llm.client import LLMClient
from valeri_api.llm.router.roles import ROLE_KB_EXTRACTION
from valeri_api.llm.structured import narrate_structured

logger = logging.getLogger("valeri.kb.extraction")


def extract_candidates(
    session: Session,
    *,
    masked_text: str,
    raw_text: str,
    masked_history: list[str] | None = None,
    customer_focus: str | None = None,
    message_id: int | None = None,
    client: LLMClient | None = None,
) -> ExtractionResult:
    """Extract facts/events/relationships from one masked utterance.

    `customer_focus` is the pseudonym of the customer currently in focus (or None).
    Logs the pass to app.kb_extraction. Raises NarrationFailed when the gateway is
    unavailable or output can't be validated within the retry budget.
    """
    payload: dict[str, Any] = {
        "poruka": masked_text,
        "prethodne_poruke": masked_history or [],
        "fokus_kupac": customer_focus,
    }
    result, model, _ = narrate_structured(
        session,
        payload,
        ExtractionResult,
        system_prompt=EXTRACTION_SYSTEM_PROMPT,
        instruction=EXTRACTION_INSTRUCTION,
        client=client,
        text_field=None,  # candidates are structured fields, not narrative numbers
        role=ROLE_KB_EXTRACTION,
    )

    # Provenance: the candidates before apply (raw_text is the real utterance, on-prem only).
    session.add(
        KBExtraction(
            message_id=message_id,
            raw_text=raw_text,
            extracted=jsonable(result.model_dump(mode="json")),
            model=model,
            confidence=result.confidence,
        )
    )
    session.flush()
    return result
