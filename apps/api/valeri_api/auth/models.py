"""SQLAlchemy model for app.app_user (M8)."""

import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Text, func, text
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from valeri_api.db import Base

user_role_enum = ENUM("owner", "sales_rep", "finance", "admin", name="user_role", create_type=False)

USER_ROLES = ("owner", "sales_rep", "finance", "admin")


class AppUser(Base):
    """A VALERI login: owner, sales rep, finance, or admin.

    A sales_rep login links to its core.sales_rep row — that link is what
    scopes a rep's visible customers/tasks (RBAC).
    """

    __tablename__ = "app_user"
    __table_args__ = {"schema": "app"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    role: Mapped[str] = mapped_column(user_role_enum, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    sales_rep_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("core.sales_rep.id"))
    # Stored from M8 (D8); the LLM-side "respond in {preferred_language}" lands in X2.
    preferred_language: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'bs'")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
