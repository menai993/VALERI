"""Chat API (M9): Ask VALERI — sessions, SSE messages, history. Per docs/api-spec.md.

All authenticated roles may chat; each user sees only their own conversations.
RBAC on DATA happens inside the tool catalog (a rep chatting still cannot reach
finance data — the tools refuse).
"""

import json
from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from valeri_api.auth.deps import CurrentUser
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
from valeri_api.db import get_session

router = APIRouter()


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
    """Send a message; the reply streams as SSE (tool_call → register → token → card? → done)."""
    conversation = _get_owned_conversation(session, session_id, user.id)

    # D3: the full pipeline runs, then events stream. The SSE contract stays the
    # same when true incremental streaming is added later.
    events = handle_message(session, user, conversation, body.text)
    session.commit()

    def event_stream() -> Iterator[str]:
        for event in events:
            payload = json.dumps(
                {"type": event.type, **event.data}, ensure_ascii=False, default=str
            )
            yield f"data: {payload}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
