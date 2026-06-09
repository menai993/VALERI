"""Relevance gate (CI1): a cheap Tier-1 filter before extraction.

Skips pure questions/greetings so the (more expensive) extraction call only runs
on messages that actually assert something — the gate cost lever from
docs/llm-cost.md §6. On any gate failure we skip capture (fail cheap, never block
the chat answer).
"""

import logging

from sqlalchemy.orm import Session

from valeri_api.kb.prompts import GATE_INSTRUCTION, GATE_SYSTEM_PROMPT
from valeri_api.kb.schemas import RelevanceDecision
from valeri_api.llm.client import LLMClient
from valeri_api.llm.router.roles import ROLE_KB_GATE
from valeri_api.llm.schemas import NarrationFailed
from valeri_api.llm.structured import narrate_structured

logger = logging.getLogger("valeri.kb.gate")


def is_relevant(session: Session, masked_text: str, client: LLMClient | None = None) -> bool:
    """True when the (already masked) message asserts something worth capturing."""
    try:
        decision, _, _ = narrate_structured(
            session,
            {"poruka": masked_text},
            RelevanceDecision,
            system_prompt=GATE_SYSTEM_PROMPT,
            instruction=GATE_INSTRUCTION,
            client=client,
            text_field=None,  # a yes/no gate renders no user-facing numbers
            role=ROLE_KB_GATE,
        )
        return decision.relevant
    except NarrationFailed as failure:
        logger.info("kb relevance gate failed (%s); skipping capture", failure.reason)
        return False
