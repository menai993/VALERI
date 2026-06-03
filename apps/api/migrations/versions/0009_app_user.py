"""Application users + RBAC roles.

M8: user_role enum + app.app_user exactly per docs/data-model.md (auth section),
plus preferred_language (D8, architecture.md §8 — stored now, wired to the LLM
in X2). Users themselves are created by the seed (dev) or via /settings/users
(admin) — never by this migration.

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

user_role_enum = ENUM("owner", "sales_rep", "finance", "admin", name="user_role", create_type=False)


def upgrade() -> None:
    user_role_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "app_user",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False, unique=True),
        sa.Column("role", user_role_enum, nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("sales_rep_id", sa.BigInteger(), sa.ForeignKey("core.sales_rep.id")),
        sa.Column("preferred_language", sa.Text(), nullable=False, server_default=sa.text("'bs'")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="app",
    )


def downgrade() -> None:
    op.drop_table("app_user", schema="app")
    user_role_enum.drop(op.get_bind(), checkfirst=True)
