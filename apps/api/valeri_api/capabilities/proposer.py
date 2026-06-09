"""The capability drafter (CSA Phase 3b): an answerable gap → a metric PROPOSAL.

When chat hits a question no registered metric covers, the LLM drafts a candidate
metric (name + Bosnian description + params + a read-only SELECT over the curated
schema). The draft is stored INERT (status='proposed') only if it passes the
static safety gate — it is NEVER auto-activated (a human approves it). The model
drafts; proposal_safety + the human approval gate keep it safe.
"""

import logging

from pydantic import ValidationError
from sqlalchemy.orm import Session

from valeri_api.auth.models import AppUser
from valeri_api.capabilities.applier import (
    InvalidProposalState,
    create_proposal,
)
from valeri_api.capabilities.models import CapabilityProposal
from valeri_api.capabilities.schemas import MetricProposalDraft, ProposalCreate
from valeri_api.llm.client import LLMClient
from valeri_api.llm.prompts import CAPABILITY_PROPOSAL_SYSTEM_PROMPT, CAPABILITY_SCHEMA_DOC
from valeri_api.llm.router.roles import ROLE_INVESTIGATION
from valeri_api.llm.schemas import NarrationFailed
from valeri_api.llm.structured import narrate_structured
from valeri_api.semantic.proposal_safety import UnsafeMetricSQL
from valeri_api.semantic.registry import available_metrics

logger = logging.getLogger("valeri.capabilities.proposer")


def propose_metric_from_question(
    session: Session,
    masked_question: str,
    user: AppUser,
    *,
    source_message_id: int | None = None,
    client: LLMClient | None = None,
) -> CapabilityProposal | None:
    """Draft + store (inert) a metric proposal for an answerable gap, or None.

    `masked_question` is already PII-masked. Returns a 'proposed' CapabilityProposal,
    or None when the model can't answer from data, the draft is malformed, the name
    already exists, or the SQL fails the safety gate. NEVER activates anything.
    """
    payload = {
        "pitanje": masked_question,
        "postojece_metrike": sorted(available_metrics(session).keys()),
        "shema": CAPABILITY_SCHEMA_DOC,
    }
    try:
        draft, _, _ = narrate_structured(
            session,
            payload,
            MetricProposalDraft,
            system_prompt=CAPABILITY_PROPOSAL_SYSTEM_PROMPT,
            instruction=(
                "Predloži novu metriku SAMO ako se na pitanje može odgovoriti jednim "
                "read-only SELECT-om nad datom šemom; inače vrati can_answer=false."
            ),
            client=client,
            text_field=None,  # SQL/identifiers are not user-facing narrated numbers
            role=ROLE_INVESTIGATION,  # Tier-2: authoring SQL is hard
        )
    except NarrationFailed as failure:
        logger.info("capability draft failed: %s", failure.reason)
        return None

    if not draft.can_answer or not draft.sql.strip() or not draft.name.strip():
        return None

    try:
        data = ProposalCreate(
            name=draft.name,
            description=draft.description or draft.name,
            entity=draft.entity,
            grain=draft.grain,
            params=draft.params,
            sql=draft.sql,
            source_message_id=source_message_id,
        )
    except ValidationError as error:
        logger.info("capability draft has an invalid shape, skipped: %s", error)
        return None

    if data.name in available_metrics(session):
        return None  # already a known metric — the gap check shouldn't have fired

    try:
        return create_proposal(session, data, user)  # static safety gate; raises if unsafe
    except (UnsafeMetricSQL, InvalidProposalState) as error:
        logger.info("capability draft rejected by safety/state, not surfaced: %s", error)
        return None
