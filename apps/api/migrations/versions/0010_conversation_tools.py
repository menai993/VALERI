"""Conversation, tool-call log, and the decision log.

M9: app.conversation + app.message + app.tool_call_log exactly per
docs/data-model.md, plus app.decision (+ decision_kind/actor_kind enums) pulled
forward from M10 (spec D1) because the tool catalog's mutation contract requires
every mutating tool to write an append-only, reversible decision.

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM, JSONB

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

register_enum = ENUM("analiza", "preporuka", "akcija", name="register", create_type=False)
decision_kind_enum = ENUM(
    "suppression",
    "threshold_change",
    "reactivation",
    "undo",
    "approval",
    "rejection",
    name="decision_kind",
    create_type=False,
)
actor_kind_enum = ENUM("valeri", "user", name="actor_kind", create_type=False)


def upgrade() -> None:
    decision_kind_enum.create(op.get_bind(), checkfirst=True)
    actor_kind_enum.create(op.get_bind(), checkfirst=True)

    # ── app.conversation ──────────────────────────────────────────────────────
    op.create_table(
        "conversation",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("title", sa.Text(), nullable=True),
        schema="app",
    )
    op.create_index("ix_conversation_user", "conversation", ["user_id"], schema="app")

    # ── app.message ───────────────────────────────────────────────────────────
    op.create_table(
        "message",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.BigInteger(),
            sa.ForeignKey("app.conversation.id"),
            nullable=False,
        ),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("register", register_enum, nullable=True),
        sa.Column("tool_calls", JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="app",
    )
    op.create_index("ix_message_conversation", "message", ["conversation_id"], schema="app")

    # ── app.tool_call_log (APPEND-ONLY) ──────────────────────────────────────
    # message_id is nullable: the M13 investigation agent calls tools outside chat.
    op.create_table(
        "tool_call_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("message_id", sa.BigInteger(), sa.ForeignKey("app.message.id"), nullable=True),
        sa.Column("tool", sa.Text(), nullable=False),
        sa.Column("args", JSONB(), nullable=True),
        sa.Column("result_ref", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="app",
    )

    # ── app.decision (APPEND-ONLY; D1 — pulled forward from M10) ─────────────
    op.create_table(
        "decision",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("kind", decision_kind_enum, nullable=False),
        sa.Column("actor", actor_kind_enum, nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("payload", JSONB(), nullable=True),
        sa.Column("reversible", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "reverted_decision_id",
            sa.BigInteger(),
            sa.ForeignKey("app.decision.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="app",
    )


def downgrade() -> None:
    op.drop_table("decision", schema="app")
    op.drop_table("tool_call_log", schema="app")
    op.drop_index("ix_message_conversation", "message", schema="app")
    op.drop_table("message", schema="app")
    op.drop_index("ix_conversation_user", "conversation", schema="app")
    op.drop_table("conversation", schema="app")
    actor_kind_enum.drop(op.get_bind(), checkfirst=True)
    decision_kind_enum.drop(op.get_bind(), checkfirst=True)
