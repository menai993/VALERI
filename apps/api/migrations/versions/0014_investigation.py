"""Investigation agent: investigations + step trace + budgets (M13).

app.investigation / app.investigation_step / inv_status exactly per docs/data-model.md,
plus one additive column (created_by — the requesting user, needed for the agent's
RBAC ToolContext) and the agent budget caps seeded into app.rule_config.

LangGraph's own checkpoint tables are NOT created here — PostgresSaver.setup()
creates them on first use (per the data-model.md note).

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-03
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Spec D3: hard caps for the agent loop — tunable in DB, never hard-coded.
INVESTIGATION_DEFAULTS = {
    "max_steps": 8,  # act iterations per investigation
    "max_seconds": 300,  # wall-clock budget
    "max_tokens": 50000,  # cumulative LLM tokens
}


def upgrade() -> None:
    # ── inv_status enum ───────────────────────────────────────────────────────
    op.execute(
        "CREATE TYPE inv_status AS ENUM ('queued', 'running', 'needs_input', 'done', 'failed')"
    )

    # ── app.investigation ─────────────────────────────────────────────────────
    op.create_table(
        "investigation",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("trigger", sa.Text(), nullable=False),  # user/auto/signal
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.dialects.postgresql.ENUM(name="inv_status", create_type=False),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("model_tier", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("report", JSONB),  # {narrative, findings[], confidence, next_step, trace_ref}
        sa.Column("thread_id", sa.Text()),  # LangGraph checkpoint thread
        # Additive (not in the illustrative DDL): who asked — drives the agent's RBAC.
        sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("app.app_user.id")),
        # Additive: the optional source signal ("Istraži" on a signal).
        sa.Column("signal_id", sa.BigInteger(), sa.ForeignKey("app.signal.id")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="app",
    )
    op.create_index("ix_investigation_status", "investigation", ["status"], schema="app")

    # ── app.investigation_step (APPEND-ONLY trace) ────────────────────────────
    op.create_table(
        "investigation_step",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "investigation_id",
            sa.BigInteger(),
            sa.ForeignKey("app.investigation.id"),
            nullable=False,
        ),
        sa.Column("step_no", sa.Integer(), nullable=False),
        sa.Column("node", sa.Text()),
        sa.Column("tool", sa.Text()),
        sa.Column("input", JSONB),
        sa.Column("output", JSONB),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="app",
    )
    op.create_index(
        "ix_investigation_step_inv", "investigation_step", ["investigation_id"], schema="app"
    )

    # ── budget caps → app.rule_config ─────────────────────────────────────────
    connection = op.get_bind()
    for param, value in INVESTIGATION_DEFAULTS.items():
        connection.execute(
            sa.text(
                "INSERT INTO app.rule_config (rule, param, value) "
                "VALUES ('investigation', :param, CAST(:value AS jsonb)) "
                "ON CONFLICT (rule, param) DO NOTHING"
            ),
            {"param": param, "value": json.dumps(value)},
        )


def downgrade() -> None:
    op.get_bind().execute(sa.text("DELETE FROM app.rule_config WHERE rule = 'investigation'"))
    op.drop_index("ix_investigation_step_inv", "investigation_step", schema="app")
    op.drop_table("investigation_step", schema="app")
    op.drop_index("ix_investigation_status", "investigation", schema="app")
    op.drop_table("investigation", schema="app")
    op.execute("DROP TYPE inv_status")
