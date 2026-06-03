"""Tasks, feedback, and the append-only task log.

M5: task_status enum, app.task, app.task_feedback, audit.task_log — exactly per
docs/data-model.md — plus per-rule task_due_days seeded into app.rule_config.

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-02
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM, JSONB

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

task_status_enum = ENUM(
    "open", "in_progress", "done", "dismissed", name="task_status", create_type=False
)
register_enum = ENUM("analiza", "preporuka", "akcija", name="register", create_type=False)

# Due-date offsets per rule (days from signal creation) — thresholds live in DB.
TASK_DUE_DAYS = {
    "customer_decline": 3,
    "sleeping_customer": 5,
    "lost_article": 7,
    "lost_category": 7,
    "narrow_basket": 14,
}


def upgrade() -> None:
    task_status_enum.create(op.get_bind(), checkfirst=True)

    # ── app.task ──────────────────────────────────────────────────────────────
    op.create_table(
        "task",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("signal_id", sa.BigInteger(), sa.ForeignKey("app.signal.id")),
        sa.Column("assignee_id", sa.BigInteger(), sa.ForeignKey("core.sales_rep.id")),
        sa.Column("owner_cc", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("proposed_action", sa.Text(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("status", task_status_enum, nullable=False, server_default=sa.text("'open'")),
        sa.Column("register", register_enum, nullable=False, server_default=sa.text("'preporuka'")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="app",
    )
    op.create_index("ix_task_assignee_status", "task", ["assignee_id", "status"], schema="app")

    # ── app.task_feedback ────────────────────────────────────────────────────
    op.create_table(
        "task_feedback",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("task_id", sa.BigInteger(), sa.ForeignKey("app.task.id"), nullable=False),
        sa.Column("useful", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("by_user", sa.BigInteger(), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="app",
    )

    # ── audit.task_log (APPEND-ONLY) ─────────────────────────────────────────
    op.create_table(
        "task_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("task_id", sa.BigInteger(), sa.ForeignKey("app.task.id")),
        sa.Column("event", sa.Text(), nullable=False),
        sa.Column("payload", JSONB(), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="audit",
    )

    # ── due-date thresholds into app.rule_config ─────────────────────────────
    connection = op.get_bind()
    for rule, days in TASK_DUE_DAYS.items():
        connection.execute(
            sa.text(
                "INSERT INTO app.rule_config (rule, param, value) "
                "VALUES (:rule, 'task_due_days', CAST(:value AS jsonb)) "
                "ON CONFLICT (rule, param) DO NOTHING"
            ),
            {"rule": rule, "value": json.dumps(days)},
        )


def downgrade() -> None:
    op.get_bind().execute(sa.text("DELETE FROM app.rule_config WHERE param = 'task_due_days'"))
    op.drop_table("task_log", schema="audit")
    op.drop_table("task_feedback", schema="app")
    op.drop_table("task", schema="app")
    task_status_enum.drop(op.get_bind(), checkfirst=True)
