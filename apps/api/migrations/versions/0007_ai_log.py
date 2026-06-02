"""The AI call log: one append-only row per LLM call.

M6: audit.ai_log exactly per docs/data-model.md. masked_input must never
contain raw PII (enforced by the masking layer + contract tests).

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM, JSONB

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

register_enum = ENUM("analiza", "preporuka", "akcija", name="register", create_type=False)


def upgrade() -> None:
    op.create_table(
        "ai_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("masked_input", JSONB(), nullable=False),
        sa.Column("output", JSONB(), nullable=True),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("register", register_enum, nullable=True),
        sa.Column("tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="audit",
    )


def downgrade() -> None:
    op.drop_table("ai_log", schema="audit")
