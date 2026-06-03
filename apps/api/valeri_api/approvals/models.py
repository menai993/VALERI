"""SQLAlchemy model for app.approval (M7)."""

import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from valeri_api.db import Base

appr_status_enum = ENUM(
    "draft",
    "pending_approval",
    "approved",
    "rejected",
    "sent",
    name="appr_status",
    create_type=False,
)

APPROVAL_STATUSES = ("draft", "pending_approval", "approved", "rejected", "sent")


class Approval(Base):
    """The gate for customer-facing items: nothing sends without an approved row.

    payload (D2) holds the thing being approved — the draft message text, the
    target customer, the channel — so every decision is auditable.
    """

    __tablename__ = "approval"
    __table_args__ = (
        Index("ix_approval_status", "status"),
        Index("ix_approval_task", "task_id"),
        {"schema": "app"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    task_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app.task.id"))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        appr_status_enum, nullable=False, server_default=text("'draft'")
    )
    payload: Mapped[dict | None] = mapped_column(JSONB)
    decided_by: Mapped[int | None] = mapped_column(BigInteger)
    decided_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
