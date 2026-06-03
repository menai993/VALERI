"""Conversation orchestration (M9): one user message → SSE events + persisted reply.

The flow (every step auditable):
  persist user msg → resolve entities (server-side) → mask → classify intent
  (Tier-1) → map pseudonym refs back to ids → dispatch tool (RBAC + logged) →
  narrate answer (number contract / template) → rehydrate → persist reply.

Narration is generated fully and then streamed (spec D3); the SSE event contract
(tool_call → register → token → card? → done) is what the frontend binds to.
"""

import logging
import re
from typing import Any

from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from valeri_api.auth.deps import visible_customer_ids
from valeri_api.auth.models import AppUser
from valeri_api.conversation.answer import narrate_answer
from valeri_api.conversation.assistant import narrate_assistant
from valeri_api.conversation.intent import classify_intent
from valeri_api.conversation.models import Conversation, Message
from valeri_api.conversation.resolution import normalise, resolve_entities
from valeri_api.conversation.schemas import SSEEvent
from valeri_api.llm.client import LLMClient
from valeri_api.llm.masking import MaskingContext, mask_text
from valeri_api.tools.base import ToolContext
from valeri_api.tools.catalog import dispatch

logger = logging.getLogger("valeri.conversation.service")

# How many previous messages give the intent router conversational context.
HISTORY_WINDOW = 6

# Default tool per intent when the model didn't pick one explicitly.
_INTENT_DEFAULT_TOOL = {
    "feedback_config": "propose_rule_change",
    "investigation": "start_investigation",
}

# Tools that are meaningless without a specific customer. If entity resolution
# couldn't bind one, we ask which customer (listing candidates) instead of
# dispatching with empty params and surfacing a raw validation error.
_CUSTOMER_REQUIRED_TOOLS = {"get_client_knowledge", "get_customer_360"}

# Common words that are not distinctive enough to match a customer on (segments,
# question words). Stored in the normalised (diacritic-free) form used for matching.
_CANDIDATE_STOPWORDS = {
    "hotel", "restoran", "kafic", "kafe", "klinika", "skola", "objekat", "objekt",
    "kupac", "kupca", "kupcu", "kupce", "kupci", "firma", "firme",
    "sta", "znas", "znate", "znamo", "kako", "koji", "koja", "koje", "ima",
    "daj", "pokazi", "reci", "mislis", "mozes", "molim", "imamo", "imali",
}


def handle_message(
    session: Session,
    user: AppUser,
    conversation: Conversation,
    message_text: str,
    client: LLMClient | None = None,
) -> list[SSEEvent]:
    """Process one user message end-to-end. Returns the ordered SSE events."""
    events: list[SSEEvent] = []

    # ── 1. persist the user message ───────────────────────────────────────────
    user_message = Message(conversation_id=conversation.id, role="user", content=message_text)
    session.add(user_message)
    session.flush()

    # Give the conversation a title from its first message.
    if conversation.title is None:
        conversation.title = message_text[:80]

    # ── 2. server-side entity resolution + masking ────────────────────────────
    context = MaskingContext()
    resolved = resolve_entities(session, message_text)
    masked_text = mask_text(message_text, resolved, context)
    masked_history = _masked_history(session, conversation, context)

    # ── 3. intent classification (Tier-1, masked) ─────────────────────────────
    classification = classify_intent(
        session, masked_text, masked_history=masked_history, client=client, user_role=user.role
    )

    # feedback_config / investigation route to their default tools when the model
    # didn't already pick one.
    tool_name = classification.tool or _INTENT_DEFAULT_TOOL.get(classification.intent)

    # Honesty gate (CSA): never dispatch query_metric with a metric the registry
    # doesn't have — that is how the router used to force-fit a wrong answer. Treat
    # an unregistered/missing metric as "no capability fits" and answer honestly.
    if tool_name == "query_metric" and not _is_known_metric(classification.params.get("metric")):
        tool_name = None

    # ── 4a. analysis → bounded multi-step agent loop (CSA Phase 2) ───────────────
    # A comparison / multi-metric / data-grounded "why" question needs several
    # SQL-backed tool calls and one synthesized answer; the deep async 'Istraži'
    # agent stays for explicit investigations.
    if classification.intent == "analysis":
        from valeri_api.conversation.agent import run_chat_agent
        from valeri_api.conversation.context import prior_context

        text, register, agent_tool_calls, _source = run_chat_agent(
            session,
            user,
            masked_text,
            context,
            message_id=user_message.id,
            prior_context=prior_context(session, conversation.id),
            client=client,
        )
        for call in agent_tool_calls:
            events.append(
                SSEEvent(type="tool_call", data={"tool": call.get("tool"), "params": call.get("params", {})})
            )
        return _finish(
            session, conversation, events, text=text, register=register, tool_calls=agent_tool_calls
        )

    # ── 4b. no fitting tool → data-aware assistant reply (read-only, no mutation) ──
    # A validly-chosen tool is dispatched even when the model tagged the intent
    # "help" (e.g. "šta sve možeš?" → describe_capabilities); only a genuinely
    # empty tool falls through to the assistant.
    if tool_name is None:
        text, register, _ = narrate_assistant(session, user, context, client=client)
        return _finish(
            session,
            conversation,
            events,
            text=text,
            register=register,
            tool_calls=[],
        )

    # ── 5. dispatch the tool (RBAC + validation + logging inside) ────────────
    params = _resolve_param_refs(classification.params, context)

    # A customer-scoped tool with no resolvable customer: first carry the customer
    # in conversational focus (a follow-up like "šta je kupio kupac?" means the one
    # we were just discussing); only if there's none do we ask which one.
    if tool_name in _CUSTOMER_REQUIRED_TOOLS and "customer_id" not in params:
        focus_id = _focus_customer_id(session, conversation, user)
        if focus_id is not None:
            params["customer_id"] = focus_id
        else:
            return _finish(
                session,
                conversation,
                events,
                text=_unresolved_customer_reply(session, user, message_text),
                register="analiza",
                tool_calls=[
                    {"tool": tool_name, "params": params, "ok": False,
                     "error_code": "unresolved_customer"}
                ],
            )

    tool_context = ToolContext(
        session=session, user=user, message_id=user_message.id, llm_client=client
    )

    events.append(SSEEvent(type="tool_call", data={"tool": tool_name, "params": params}))
    tool_result = dispatch(tool_context, tool_name, params)

    # ── 6. narrate the answer (masked → validated → rehydrated) ──────────────
    text, register, source = narrate_answer(session, tool_result, context, client=client)

    tool_call_record = {
        "tool": tool_name,
        "params": params,
        "ok": tool_result.ok,
        "error_code": tool_result.error_code,
        "narration_source": source,
    }

    # Successful mutations show up as inline cards (register + status visible).
    card: dict[str, Any] | None = None
    if tool_result.ok and tool_name == "create_task_draft":
        card = {"card_type": "task_draft", "payload": tool_result.output}
    elif tool_result.ok and tool_name == "propose_rule_change":
        card = {"card_type": "rule_proposal", "payload": tool_result.output}
    elif tool_result.ok and tool_name == "start_investigation":
        card = {"card_type": "investigation", "payload": tool_result.output}

    return _finish(
        session,
        conversation,
        events,
        text=text,
        register=register,
        tool_calls=[tool_call_record],
        card=card,
    )


# ── helpers ───────────────────────────────────────────────────────────────────


def _is_known_metric(metric: Any) -> bool:
    """True iff `metric` is a registered semantic-layer metric (honesty gate)."""
    if not metric:
        return False
    from valeri_api.semantic.registry import load_registry

    return metric in load_registry()


def _masked_history(
    session: Session, conversation: Conversation, context: MaskingContext
) -> list[str]:
    """The last few messages, re-masked (stored messages are rehydrated/human-facing)."""
    rows = (
        session.query(Message)
        .filter(Message.conversation_id == conversation.id)
        .order_by(Message.id.desc())
        .offset(1)  # skip the message we just stored
        .limit(HISTORY_WINDOW)
        .all()
    )
    history = []
    for message in reversed(rows):
        if not message.content:
            continue
        resolved = resolve_entities(session, message.content)
        history.append(f"{message.role}: {mask_text(message.content, resolved, context)}")
    return history


def _focus_customer_id(session: Session, conversation: Conversation, user: AppUser) -> int | None:
    """The customer currently in conversational focus: the most recently mentioned one.

    Lets a pronoun/anaphor follow-up ("šta je kupio kupac?") resolve to the customer
    just discussed instead of re-asking. RBAC-scoped: a rep never inherits a focus
    customer outside their book.
    """
    scope = visible_customer_ids(user, session)
    rows = (
        session.query(Message)
        .filter(Message.conversation_id == conversation.id)
        .order_by(Message.id.desc())
        .limit(HISTORY_WINDOW)
        .all()
    )
    for message in rows:
        if not message.content:
            continue
        for _matched, customer_id, _name in resolve_entities(session, message.content):
            if scope is None or customer_id in scope:
                return customer_id
    return None


def _customer_candidates(session: Session, user: AppUser, message_text: str) -> list[str]:
    """Customers whose name shares a distinctive token with the message (RBAC-scoped).

    Cheap, deterministic disambiguation source: for a mention like "hotel aria" that
    spans several objects, this returns those objects so we can ask which one.
    """
    tokens = {
        token
        for token in re.findall(r"[0-9a-zčćžšđ]+", normalise(message_text))
        if len(token) >= 4 and token not in _CANDIDATE_STOPWORDS
    }
    if not tokens:
        return []

    scope = visible_customer_ids(user, session)
    rows = session.execute(sql_text("SELECT id, name FROM core.customer ORDER BY id")).all()
    candidates = [
        name
        for customer_id, name in ((row.id, row.name) for row in rows)
        if (scope is None or customer_id in scope)
        and any(token in normalise(name) for token in tokens)
    ]
    return candidates[:6]


def _unresolved_customer_reply(session: Session, user: AppUser, message_text: str) -> str:
    """A short Bosnian clarification when a customer-scoped question names no clear customer."""
    candidates = _customer_candidates(session, user, message_text)
    if candidates:
        listed = ", ".join(candidates)
        return (
            "Nisam siguran na kojeg tačno kupca mislite — pronašao sam više mogućnosti: "
            f"{listed}. Na kojeg mislite? Navedite tačan naziv."
        )
    return (
        "Nisam prepoznao kupca u Vašem pitanju. Možete li navesti tačan naziv kupca "
        "(kako je zaveden u bazi)?"
    )


def _resolve_param_refs(params: dict[str, Any], context: MaskingContext) -> dict[str, Any]:
    """Map pseudonym customer refs the model produced back to real ids (server-side)."""
    resolved = dict(params)
    customer_ref = resolved.pop("customer_ref", None)
    if customer_ref:
        customer_id = context.customer_id_for(str(customer_ref))
        if customer_id is not None:
            resolved["customer_id"] = customer_id
        # An unknown/invented pseudonym resolves to nothing — the tool's own
        # validation/RBAC will reject or scope the call (never trust the model).
    return resolved


def _finish(
    session: Session,
    conversation: Conversation,
    events: list[SSEEvent],
    text: str,
    register: str,
    tool_calls: list[dict[str, Any]],
    card: dict[str, Any] | None = None,
) -> list[SSEEvent]:
    """Persist the assistant reply and emit the closing SSE events."""
    reply = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=text,
        register=register,
        tool_calls=tool_calls,
    )
    session.add(reply)
    session.flush()

    events.append(SSEEvent(type="register", data={"register": register}))
    events.append(SSEEvent(type="token", data={"text": text}))
    if card is not None:
        events.append(SSEEvent(type="card", data=card))
    events.append(
        SSEEvent(
            type="done",
            data={"message_id": reply.id, "register": register, "tool_calls": tool_calls},
        )
    )
    return events
