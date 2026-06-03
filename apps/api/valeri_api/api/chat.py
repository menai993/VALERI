"""Chat API (M9): Ask VALERI — sessions, SSE messages, history. Per docs/api-spec.md.

All authenticated roles may chat; each user sees only their own conversations.
RBAC on DATA happens inside the tool catalog (a rep chatting still cannot reach
finance data — the tools refuse).
"""

import json
import logging
from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
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
)
from valeri_api.conversation.service import handle_message
from valeri_api.db import get_session, session_scope

logger = logging.getLogger("valeri.api.chat")

router = APIRouter()


def _capture_from_message(message_id: int, user_id: int, message_text: str) -> None:
    """CI1: run knowledge capture on a chat message, async + non-blocking.

    Its own short-lived session (the request's is closed once the response streams).
    Capture must never break the chat reply — any failure is logged and swallowed.
    """
    from valeri_api.kb.pipeline import run_capture

    try:
        with session_scope() as session:
            run_capture(session, text_in=message_text, user_id=user_id, message_id=message_id)
    except Exception:  # noqa: BLE001 — capture is best-effort, never fatal to chat
        logger.exception("kb capture failed for message %s", message_id)


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
    background_tasks: BackgroundTasks,
    session: Annotated[Session, Depends(get_session)],
    user: CurrentUser,
) -> StreamingResponse:
    """Send a message; the reply streams as SSE (tool_call → register → token → card? → done)."""
    conversation = _get_owned_conversation(session, session_id, user.id)

    # D3: the full pipeline runs, then events stream. The SSE contract stays the
    # same when true incremental streaming is added later.
    events = handle_message(session, user, conversation, body.text)
    session.commit()

    # CI1: capture knowledge from the message in the background (non-blocking).
    # Prod-only — capture needs the gateway; with narration off (e.g. tests) it's skipped.
    if get_settings().llm_narration_enabled:
        user_message_id = session.execute(
            select(Message.id)
            .where(Message.conversation_id == conversation.id, Message.role == "user")
            .order_by(Message.id.desc())
            .limit(1)
        ).scalar()
        if user_message_id is not None:
            background_tasks.add_task(_capture_from_message, user_message_id, user.id, body.text)

    def event_stream() -> Iterator[str]:
        for event in events:
            payload = json.dumps(
                {"type": event.type, **event.data}, ensure_ascii=False, default=str
            )
            yield f"data: {payload}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
