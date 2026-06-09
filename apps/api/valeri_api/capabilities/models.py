"""SQLAlchemy model for app.capability_proposal (CSA Phase 3a)."""

import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from valeri_api.db import Base


class CapabilityProposal(Base):
    """A self-proposed metric. INERT (status='proposed') until a human approves it."""

    __tablename__ = "capability_proposal"
    __table_args__ = {"schema": "app"}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)  # Bosnian
    entity: Mapped[str] = mapped_column(Text, nullable=False)
    grain: Mapped[str] = mapped_column(Text, nullable=False)
    params: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    sql: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="proposed")
    source_message_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app.message.id"))
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    decision_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app.decision.id"))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    activated_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
