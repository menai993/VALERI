"""Phase-2 CRM: opportunities + pipeline (C-CRM1).

opp_stage enum + app.opportunity / app.opportunity_stage_history / app.activity
exactly per docs/data-model.md (Phase-2 CRM section), plus stage→default-probability
seeds in app.rule_config (never hard-coded). The activity table is created here
(same Phase-2 DDL block, one migration per schema milestone) but is used in C-CRM2.

This track introduces NO LLM: opportunities are VALERI-native user data; the ERP
stays read-only.

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-03
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM, JSONB

# revision identifiers, used by Alembic.
revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Spec D2: stage → default probability. An opportunity's explicit probability
# overrides this; tunable in app.rule_config, never in code.
STAGE_PROBABILITY = {
    "lead": 0.10,
    "qualified": 0.30,
    "proposal": 0.50,
    "negotiation": 0.70,
    "won": 1.0,
    "lost": 0.0,
}


def upgrade() -> None:
    # ── opp_stage enum ────────────────────────────────────────────────────────
    op.execute(
        "CREATE TYPE opp_stage AS ENUM "
        "('lead', 'qualified', 'proposal', 'negotiation', 'won', 'lost')"
    )
    opp_stage = ENUM(name="opp_stage", create_type=False)

    # ── app.opportunity ───────────────────────────────────────────────────────
    op.create_table(
        "opportunity",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "customer_id", sa.BigInteger(), sa.ForeignKey("core.customer.id"), nullable=False
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("value", sa.Numeric(14, 2)),
        sa.Column("probability", sa.Numeric(5, 4)),
        sa.Column("stage", opp_stage, nullable=False, server_default="lead"),
        sa.Column("source", sa.Text()),  # referral/inbound/...
        sa.Column("expected_close", sa.Date()),
        sa.Column("owner_rep_id", sa.BigInteger(), sa.ForeignKey("core.sales_rep.id")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="app",
    )
    op.create_index("ix_opportunity_customer", "opportunity", ["customer_id"], schema="app")
    op.create_index("ix_opportunity_stage", "opportunity", ["stage"], schema="app")
    op.create_index("ix_opportunity_owner_rep", "opportunity", ["owner_rep_id"], schema="app")

    # ── app.opportunity_stage_history (APPEND-ONLY) ───────────────────────────
    op.create_table(
        "opportunity_stage_history",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "opportunity_id",
            sa.BigInteger(),
            sa.ForeignKey("app.opportunity.id"),
            nullable=False,
        ),
        sa.Column("stage", opp_stage, nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="app",
    )
    op.create_index(
        "ix_opp_stage_history_opp", "opportunity_stage_history", ["opportunity_id"], schema="app"
    )

    # ── app.activity (created now; used in C-CRM2) ────────────────────────────
    op.create_table(
        "activity",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "sales_rep_id", sa.BigInteger(), sa.ForeignKey("core.sales_rep.id"), nullable=False
        ),
        sa.Column("customer_id", sa.BigInteger(), sa.ForeignKey("core.customer.id")),
        sa.Column("kind", sa.Text(), nullable=False),  # meeting/call/offer/follow_up/analysis
        sa.Column("done", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="app",
    )
    op.create_index("ix_activity_rep", "activity", ["sales_rep_id"], schema="app")

    # ── stage probabilities → app.rule_config ─────────────────────────────────
    op.get_bind().execute(
        sa.text(
            "INSERT INTO app.rule_config (rule, param, value) "
            "VALUES ('crm', 'stage_probability', CAST(:value AS jsonb)) "
            "ON CONFLICT (rule, param) DO NOTHING"
        ),
        {"value": json.dumps(STAGE_PROBABILITY)},
    )
    # The JSONB import is referenced so the column type is registered for autogen.
    _ = JSONB


def downgrade() -> None:
    op.get_bind().execute(sa.text("DELETE FROM app.rule_config WHERE rule = 'crm'"))
    op.drop_index("ix_activity_rep", "activity", schema="app")
    op.drop_table("activity", schema="app")
    op.drop_index("ix_opp_stage_history_opp", "opportunity_stage_history", schema="app")
    op.drop_table("opportunity_stage_history", schema="app")
    op.drop_index("ix_opportunity_owner_rep", "opportunity", schema="app")
    op.drop_index("ix_opportunity_stage", "opportunity", schema="app")
    op.drop_index("ix_opportunity_customer", "opportunity", schema="app")
    op.drop_table("opportunity", schema="app")
    op.execute("DROP TYPE opp_stage")
