"""Conversation orchestration (M9): one user message → SSE events + persisted reply.

The flow (every step auditable):
  persist user msg → resolve entities (server-side) → mask → classify intent
  (Tier-1) → map pseudonym refs back to ids → dispatch tool (RBAC + logged) →
  narrate answer (number contract / template) → rehydrate → persist reply.

Narration is generated fully and then streamed (spec D3); the SSE event contract
(tool_call → register → token → card? → done) is what the frontend binds to.
"""

import logging
from typing import Any

from sqlalchemy.orm import Session

from valeri_api.auth.models import AppUser
from valeri_api.conversation.answer import HELP_TEXT, narrate_answer
from valeri_api.conversation.intent import classify_intent
from valeri_api.conversation.models import Conversation, Message
from valeri_api.conversation.resolution import resolve_entities
from valeri_api.conversation.schemas import SSEEvent
from valeri_api.llm.client import LLMClient
from valeri_api.llm.masking import MaskingContext, mask_text
from valeri_api.tools.base import ToolContext
from valeri_api.tools.catalog import dispatch

logger = logging.getLogger("valeri.conversation.service")

# How many previous messages give the intent router conversational context.
HISTORY_WINDOW = 6

# Intents that the stub tools serve until their milestone lands.
_INTENT_DEFAULT_TOOL = {
    "feedback_config": "propose_rule_change",
    "investigation": "start_investigation",
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
        session, masked_text, masked_history=masked_history, client=client
    )

    # feedback_config / investigation route to their stub tools when the model
    # didn't already pick one.
    tool_name = classification.tool or _INTENT_DEFAULT_TOOL.get(classification.intent)

    # ── 4. help / no tool → static guidance, no data access ──────────────────
    if classification.intent == "help" or tool_name is None:
        return _finish(
            session,
            conversation,
            events,
            text=HELP_TEXT,
            register="analiza",
            tool_calls=[],
        )

    # ── 5. dispatch the tool (RBAC + validation + logging inside) ────────────
    params = _resolve_param_refs(classification.params, context)
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
