"""SQLAlchemy model for app.tool_call_log (M9). APPEND-ONLY."""

import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from valeri_api.db import Base


class ToolCallLog(Base):
    """One tool invocation — success or failure. Rows are only ever inserted.

    message_id is nullable: the investigation agent (M13) calls tools outside chat.
    """

    __tablename__ = "tool_call_log"
    __table_args__ = {"schema": "app"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    message_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app.message.id"))
    tool: Mapped[str] = mapped_column(Text, nullable=False)
    args: Mapped[dict | None] = mapped_column(JSONB)
    result_ref: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
