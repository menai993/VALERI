"""SQLAlchemy models for app.conversation and app.message (M9)."""

import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from valeri_api.db import Base

register_enum = ENUM("analiza", "preporuka", "akcija", name="register", create_type=False)

MESSAGE_ROLES = ("user", "assistant")


class Conversation(Base):
    """One chat session, owned by one user."""

    __tablename__ = "conversation"
    __table_args__ = (
        Index("ix_conversation_user", "user_id"),
        {"schema": "app"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    started_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    title: Mapped[str | None] = mapped_column(Text)


class Message(Base):
    """One chat message; assistant messages carry a register + their tool calls."""

    __tablename__ = "message"
    __table_args__ = (
        Index("ix_message_conversation", "conversation_id"),
        {"schema": "app"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("app.conversation.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    register: Mapped[str | None] = mapped_column(register_enum)
    tool_calls: Mapped[list | None] = mapped_column(JSONB)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
