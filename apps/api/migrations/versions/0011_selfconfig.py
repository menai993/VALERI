"""Self-configuration: suppression hits + autonomy thresholds.

M10: app.suppression_hit exactly per docs/data-model.md (each scanner suppression
records which learned rule hid which persisted suppressed signal), plus the
graduated-autonomy boundary seeded into app.rule_config (never hard-coded).

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-03
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The auto-apply vs confirm boundary (spec D4). Lives in DB so it is tunable
# without code changes; "confirm_kinds" always require a one-tap human confirm.
SELFCONFIG_DEFAULTS = {
    "auto_apply_max_effect": 10,  # max signals (last 90d) a scope may hide to auto-apply
    "auto_apply_min_confidence": 0.7,  # min interpretation confidence to auto-apply
    "confirm_kinds": ["category", "threshold", "conditional"],
    "effect_window_days": 90,  # the blast-radius lookback window
}


def upgrade() -> None:
    # ── app.suppression_hit (APPEND-ONLY) ─────────────────────────────────────
    op.create_table(
        "suppression_hit",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "learned_rule_id",
            sa.BigInteger(),
            sa.ForeignKey("app.learned_rule.id"),
            nullable=False,
        ),
        sa.Column("signal_id", sa.BigInteger(), sa.ForeignKey("app.signal.id"), nullable=True),
        sa.Column(
            "suppressed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="app",
    )
    op.create_index("ix_suppression_hit_rule", "suppression_hit", ["learned_rule_id"], schema="app")

    # ── selfconfig autonomy thresholds → app.rule_config ─────────────────────
    connection = op.get_bind()
    for param, value in SELFCONFIG_DEFAULTS.items():
        connection.execute(
            sa.text(
                "INSERT INTO app.rule_config (rule, param, value) "
                "VALUES ('selfconfig', :param, CAST(:value AS jsonb)) "
                "ON CONFLICT (rule, param) DO NOTHING"
            ),
            {"param": param, "value": json.dumps(value)},
        )


def downgrade() -> None:
    op.get_bind().execute(sa.text("DELETE FROM app.rule_config WHERE rule = 'selfconfig'"))
    op.drop_index("ix_suppression_hit_rule", "suppression_hit", schema="app")
    op.drop_table("suppression_hit", schema="app")
