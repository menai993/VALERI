"""Owner report + approval workflow.

M7: appr_status enum, app.approval (per docs/data-model.md + payload JSONB, D2)
and app.owner_report (D1 — the stored weekly report snapshot).

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM, JSONB

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

appr_status_enum = ENUM(
    "draft",
    "pending_approval",
    "approved",
    "rejected",
    "sent",
    name="appr_status",
    create_type=False,
)


def upgrade() -> None:
    appr_status_enum.create(op.get_bind(), checkfirst=True)

    # ── app.approval — gates customer-facing drafts ───────────────────────────
    op.create_table(
        "approval",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("task_id", sa.BigInteger(), sa.ForeignKey("app.task.id")),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", appr_status_enum, nullable=False, server_default=sa.text("'draft'")),
        sa.Column("payload", JSONB(), nullable=True),
        sa.Column("decided_by", sa.BigInteger(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        schema="app",
    )
    op.create_index("ix_approval_status", "approval", ["status"], schema="app")
    op.create_index("ix_approval_task", "approval", ["task_id"], schema="app")

    # ── app.owner_report — one immutable snapshot per week ───────────────────
    op.create_table(
        "owner_report",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("week_end", sa.Date(), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("payload", JSONB(), nullable=False),
        sa.UniqueConstraint("week_start", "week_end", name="ux_owner_report_week"),
        schema="app",
    )


def downgrade() -> None:
    op.drop_table("owner_report", schema="app")
    op.drop_index("ix_approval_task", "approval", schema="app")
    op.drop_index("ix_approval_status", "approval", schema="app")
    op.drop_table("approval", schema="app")
    appr_status_enum.drop(op.get_bind(), checkfirst=True)
