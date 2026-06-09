"""CSA Phase 3b: the agent drafts a metric for an answerable gap (inert, human-approved)."""

import json

from valeri_api.capabilities.proposer import propose_metric_from_question
from valeri_api.conversation.models import Conversation
from valeri_api.conversation.service import handle_message
from valeri_api.llm.client import LLMResponse
from valeri_api.semantic.registry import resolve_metric

_GOOD_DRAFT = {
    "can_answer": True,
    "name": "invoices_per_segment",
    "description": "Broj faktura po segmentu za period",
    "entity": "segment",
    "grain": "series",
    "params": [
        {"name": "from_date", "type": "date", "required": True},
        {"name": "to_date", "type": "date", "required": True},
    ],
    "sql": (
        "SELECT c.segment, COUNT(*) AS broj FROM core.invoice i "
        "JOIN core.customer c ON c.id = i.customer_id "
        "WHERE i.date > :from_date AND i.date <= :to_date GROUP BY c.segment"
    ),
    "reasoning": "Može se odgovoriti jednim SELECT-om.",
}


class DraftFake:
    """Returns a scripted MetricProposalDraft for the capability-drafting call."""

    def __init__(self, draft: dict) -> None:
        self.draft = draft
        self.model = "fake-tier2"
        self.captured: list[dict] = []

    def complete(self, system: str, user: str) -> LLMResponse:
        self.captured.append({"system": system, "user": user})
        return LLMResponse(
            text=json.dumps(self.draft, ensure_ascii=False),
            model=self.model,
            tokens=100,
            latency_ms=50,
        )


def test_answerable_gap_drafts_inert_proposal(owner_context) -> None:
    session, user = owner_context.session, owner_context.user
    proposal = propose_metric_from_question(
        session, "koliko faktura po segmentu?", user, client=DraftFake(_GOOD_DRAFT)
    )
    assert proposal is not None
    assert proposal.name == "invoices_per_segment"
    assert proposal.status == "proposed"  # INERT — never auto-active
    assert resolve_metric(session, "invoices_per_segment") is None  # not yet in the vocabulary


def test_non_answerable_returns_none(owner_context) -> None:
    fake = DraftFake({"can_answer": False, "reasoning": "ne može se odgovoriti iz podataka"})
    assert (
        propose_metric_from_question(
            owner_context.session, "kakvo je vrijeme?", owner_context.user, client=fake
        )
        is None
    )


def test_unsafe_draft_not_surfaced(owner_context) -> None:
    unsafe = {**_GOOD_DRAFT, "name": "evil_x", "sql": "DELETE FROM core.invoice"}
    assert (
        propose_metric_from_question(
            owner_context.session, "obriši fakture", owner_context.user, client=DraftFake(unsafe)
        )
        is None
    )


def test_pii_draft_not_surfaced(owner_context) -> None:
    pii = {**_GOOD_DRAFT, "name": "emails_x", "sql": "SELECT c.email FROM core.customer c"}
    assert (
        propose_metric_from_question(
            owner_context.session, "daj mi mejlove", owner_context.user, client=DraftFake(pii)
        )
        is None
    )


def test_existing_metric_name_not_reproposed(owner_context) -> None:
    dup = {**_GOOD_DRAFT, "name": "turnover"}  # already a built-in metric
    assert (
        propose_metric_from_question(
            owner_context.session, "promet?", owner_context.user, client=DraftFake(dup)
        )
        is None
    )


class ChatGapFake:
    """Routes by system prompt: intent → question/no-tool; drafter → a good metric draft."""

    def __init__(self) -> None:
        self.model = "fake-tier1"
        self.captured: list[dict] = []

    def complete(self, system: str, user: str) -> LLMResponse:
        self.captured.append({"system": system, "user": user})
        if "usmjerivač namjera" in system:
            body: dict = {"intent": "question", "tool": None, "params": {}, "confidence": 0.4}
        elif "dizajner metrika" in system:
            body = _GOOD_DRAFT
        else:
            body = {"text": "Pregled iz baze.", "register": "analiza"}
        return LLMResponse(
            text=json.dumps(body, ensure_ascii=False), model=self.model, tokens=100, latency_ms=50
        )


def test_chat_gap_emits_capability_proposal_card(owner_context) -> None:
    session, user = owner_context.session, owner_context.user
    conversation = Conversation(user_id=user.id)
    session.add(conversation)
    session.flush()

    events = handle_message(
        session, user, conversation, "koliko faktura po segmentu?", client=ChatGapFake()
    )
    cards = [e for e in events if e.type == "card"]
    assert cards and cards[0].data["card_type"] == "capability_proposal"
    assert cards[0].data["payload"]["name"] == "invoices_per_segment"
