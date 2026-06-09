"""Chat API (M9): Ask VALERI — sessions, SSE messages, history. Per docs/api-spec.md.

All authenticated roles may chat; each user sees only their own conversations.
RBAC on DATA happens inside the tool catalog (a rep chatting still cannot reach
finance data — the tools refuse).
"""

import json
import logging
from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from valeri_api.auth.deps import CurrentUser
from valeri_api.config import get_settings
from valeri_api.conversation.models import Conversation, Message
from valeri_api.conversation.schemas import (
    MessageCreate,
    MessageRead,
    SessionCreateResponse,
    SessionHistoryResponse,
    SessionListResponse,
    SessionSummary,
    SSEEvent,
)
from valeri_api.conversation.service import handle_message
from valeri_api.db import get_session, session_scope

logger = logging.getLogger("valeri.api.chat")

router = APIRouter()


def _capture_label(item: object) -> str:
    """A short label for a captured fact/event (title) or relationship."""
    title = getattr(item, "title", None)
    if title:
        return str(title)
    return (
        f"{getattr(item, 'from_name', '?')} → {getattr(item, 'to_name', '?')} "
        f"({getattr(item, 'rel_type', 'veza')})"
    )


def _capture_event(message_id: int, user_id: int, message_text: str) -> SSEEvent | None:
    """CI1/CI2: capture knowledge synchronously in its OWN session (isolated from the
    chat transaction), and return a 'capture' SSE event when something was captured.

    Runs in its own session_scope so a capture failure can never corrupt the reply;
    run_capture already swallows extraction failures (audit preserved). Returns None
    (no chip) when nothing was captured.
    """
    from valeri_api.kb.pipeline import run_capture

    try:
        with session_scope() as session:
            captured = run_capture(
                session, text_in=message_text, user_id=user_id, message_id=message_id
            )
            total = len(captured.auto_saved) + len(captured.proposed) + len(captured.clarifications)
            if total == 0:
                return None
            return SSEEvent(
                type="capture",
                data={
                    "auto_saved": len(captured.auto_saved),
                    "proposed": len(captured.proposed),
                    "clarifications": len(captured.clarifications),
                    "titles": [
                        _capture_label(i) for i in (*captured.auto_saved, *captured.proposed)
                    ][:5],
                },
            )
    except Exception:  # noqa: BLE001 — capture is best-effort, never fatal to chat
        logger.exception("kb capture failed for message %s", message_id)
        return None


def _get_owned_conversation(session: Session, conversation_id: int, user_id: int) -> Conversation:
    conversation = session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": f"Razgovor {conversation_id} ne postoji"},
        )
    if conversation.user_id != user_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "forbidden", "message": "Nemate pristup ovom razgovoru"},
        )
    return conversation


@router.post("/chat/sessions", status_code=201, response_model=SessionCreateResponse)
def create_session(
    session: Annotated[Session, Depends(get_session)],
    user: CurrentUser,
) -> SessionCreateResponse:
    """Start a new chat session for the current user."""
    conversation = Conversation(user_id=user.id)
    session.add(conversation)
    session.commit()
    session.refresh(conversation)
    return SessionCreateResponse(session_id=conversation.id)


@router.get("/chat/sessions", response_model=SessionListResponse)
def list_sessions(
    session: Annotated[Session, Depends(get_session)],
    user: CurrentUser,
) -> SessionListResponse:
    """The current user's chat sessions, newest first (spec D5)."""
    conversations = session.execute(
        select(Conversation).where(Conversation.user_id == user.id).order_by(Conversation.id.desc())
    ).scalars()
    return SessionListResponse(items=[SessionSummary.model_validate(c) for c in conversations])


@router.get("/chat/sessions/{session_id}", response_model=SessionHistoryResponse)
def get_history(
    session_id: int,
    session: Annotated[Session, Depends(get_session)],
    user: CurrentUser,
) -> SessionHistoryResponse:
    """Full message history of one owned session."""
    conversation = _get_owned_conversation(session, session_id, user.id)
    messages = session.execute(
        select(Message).where(Message.conversation_id == session_id).order_by(Message.id)
    ).scalars()
    return SessionHistoryResponse(
        id=conversation.id,
        title=conversation.title,
        started_at=conversation.started_at,
        messages=[MessageRead.model_validate(message) for message in messages],
    )


@router.post("/chat/sessions/{session_id}/messages")
def post_message(
    session_id: int,
    body: MessageCreate,
    session: Annotated[Session, Depends(get_session)],
    user: CurrentUser,
) -> StreamingResponse:
    """Send a message; the reply streams as SSE (tool_call → register → token → capture? → done)."""
    conversation = _get_owned_conversation(session, session_id, user.id)

    # D3: the full pipeline runs, then events stream. The SSE contract stays the
    # same when true incremental streaming is added later.
    events = handle_message(session, user, conversation, body.text)
    session.commit()  # the answer (+ the user message) are persisted first

    # CI1/CI2: capture knowledge synchronously in its own session, then surface what
    # was captured inline (the capture chip) — committed before the reply closes, so
    # the review queue refetch never races it. Prod-only (needs the gateway; tests skip).
    if get_settings().llm_narration_enabled:
        user_message_id = session.execute(
            select(Message.id)
            .where(Message.conversation_id == conversation.id, Message.role == "user")
            .order_by(Message.id.desc())
            .limit(1)
        ).scalar()
        if user_message_id is not None:
            capture_event = _capture_event(user_message_id, user.id, body.text)
            if capture_event is not None and events and events[-1].type == "done":
                events.insert(-1, capture_event)  # right before 'done'

    def event_stream() -> Iterator[str]:
        for event in events:
            payload = json.dumps(
                {"type": event.type, **event.data}, ensure_ascii=False, default=str
            )
            yield f"data: {payload}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
