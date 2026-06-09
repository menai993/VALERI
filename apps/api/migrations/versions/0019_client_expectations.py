"""Client Intelligence CI2: per-client behavioral expectations + graph-rule config.

Adds core.client_expectation (a SQL-recomputed snapshot of what VALERI expects
from each customer — interval, gap, stretch, early-decline flag) and seeds the
thresholds for the graph-aware rules (group_risk, behavioral_twin_warning,
referral_source_risk) + client_expectation in app.rule_config (never hard-coded).

Numbers are produced in SQL (the recompute), never by the LLM.

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-03
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Spec D6: graph-rule + expectation thresholds (tunable in app.rule_config).
RULE_THRESHOLDS = {
    "group_risk": {
        "decline_ratio": 0.7,  # group turnover < 70% of baseline → at risk
        "min_members": 2,  # a group needs ≥ this many confirmed-linked objects
        "conf": 0.7,  # signal confidence for a group-risk hit
    },
    "behavioral_twin_warning": {
        "stretch_ratio": 1.5,  # a twin showing interval stretch ≥ this fires early warning
        "conf": 0.6,
    },
    "referral_source_risk": {
        "quiet_days": 60,  # a referrer silent ≥ this long puts its referrals at risk
        "conf": 0.6,
    },
    "client_expectation": {
        "early_decline_stretch": 1.4,  # gap ≥ 1.4× expected interval → early-decline sign
    },
}


def upgrade() -> None:
    op.create_table(
        "client_expectation",
        sa.Column(
            "customer_id",
            sa.BigInteger(),
            sa.ForeignKey("core.customer.id"),
            primary_key=True,
        ),
        sa.Column("expected_interval_d", sa.Numeric(8, 2)),
        sa.Column("expected_categories", JSONB()),
        sa.Column("gap_days", sa.Integer()),
        sa.Column("stretch_ratio", sa.Numeric(6, 3)),
        sa.Column("early_decline", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        schema="core",
    )

    bind = op.get_bind()
    for rule, params in RULE_THRESHOLDS.items():
        for param, value in params.items():
            bind.execute(
                sa.text(
                    "INSERT INTO app.rule_config (rule, param, value) "
                    "VALUES (:rule, :param, CAST(:value AS jsonb)) "
                    "ON CONFLICT (rule, param) DO NOTHING"
                ),
                {"rule": rule, "param": param, "value": json.dumps(value)},
            )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM app.rule_config WHERE rule IN "
            "('group_risk', 'behavioral_twin_warning', 'referral_source_risk', "
            "'client_expectation')"
        )
    )
    op.drop_table("client_expectation", schema="core")
