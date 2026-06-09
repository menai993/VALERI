"""Capability self-configuration: app.capability_proposal (CSA Phase 3a).

A self-proposed metric: drafted (status 'proposed'), INERT until a human
approves it (status 'active') — only then does it join the registry overlay and
become runnable through the validated query builder. Every state change writes a
reversible app.decision (reuses existing decision kinds; no enum change).

Revision ID: 0022
Revises: 0021
Create Date: 2026-06-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "capability_proposal",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),  # Bosnian
        sa.Column("entity", sa.Text(), nullable=False),
        sa.Column("grain", sa.Text(), nullable=False),
        sa.Column("params", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("sql", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="proposed"),
        sa.Column("source_message_id", sa.BigInteger(), sa.ForeignKey("app.message.id")),
        sa.Column("created_by", sa.BigInteger()),
        sa.Column("decision_id", sa.BigInteger(), sa.ForeignKey("app.decision.id")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        schema="app",
    )
    op.create_index(
        "ix_capability_proposal_active",
        "capability_proposal",
        ["status"],
        unique=False,
        schema="app",
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("ix_capability_proposal_active", table_name="capability_proposal", schema="app")
    op.drop_table("capability_proposal", schema="app")
