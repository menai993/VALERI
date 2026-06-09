"""Tier-1 intent classification (M9): masked text → {intent, tool, params}.

The model never answers the question here and never touches data — it only picks
a tool + parameters from the catalog whitelist. Malformed output is rejected and
retried (M6 discipline); persistent failure degrades to intent='help'.
"""

import datetime
import logging

from sqlalchemy.orm import Session

from valeri_api.conversation.schemas import IntentClassification
from valeri_api.llm.client import LLMClient
from valeri_api.llm.prompts import INTENT_SYSTEM_PROMPT
from valeri_api.llm.schemas import NarrationFailed
from valeri_api.llm.structured import narrate_structured

logger = logging.getLogger("valeri.conversation.intent")

HELP_FALLBACK = IntentClassification(intent="help", tool=None, params={}, confidence=0.0)


def classify_intent(
    session: Session,
    masked_text: str,
    masked_history: list[str] | None = None,
    client: LLMClient | None = None,
    user_role: str = "owner",
) -> IntentClassification:
    """Classify one (already masked) user message. Returns HELP_FALLBACK on failure.

    The available metrics are injected from the capability catalog (RBAC-filtered by
    `user_role`), so a newly registered metric is known to the router without a
    prompt edit (CSA: capabilities are data).
    """
    from valeri_api.semantic.capabilities import list_capabilities

    available_metrics = [
        {"naziv": cap.name, "opis": cap.description, "parametri": cap.params}
        for cap in list_capabilities(session, user_role)
        if cap.kind == "metric"
    ]
    payload = {
        "danas": str(datetime.date.today()),
        "poruka": masked_text,
        "prethodne_poruke": masked_history or [],
        "dostupne_metrike": available_metrics,
    }

    try:
        classification, _, _ = narrate_structured(
            session,
            payload,
            IntentClassification,
            system_prompt=INTENT_SYSTEM_PROMPT,
            instruction=(
                "Klasifikuj sljedeću korisničku poruku i odaberi alat + parametre. "
                "Današnji datum je naveden u polju 'danas'."
            ),
            client=client,
            text_field=None,  # classification carries no narrative numbers
            role="intent",  # M12: Tier-1 by role
        )
        return classification
    except NarrationFailed as failure:
        logger.warning("intent classification failed (%s); falling back to help", failure.reason)
        return HELP_FALLBACK
