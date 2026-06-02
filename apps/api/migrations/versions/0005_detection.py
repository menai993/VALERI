"""Detection foundation: enums, app.rule_config, app.signal, app.learned_rule.

M4: the rule engine's tables. rule_config holds every detection threshold
(never hard-coded in rule bodies) and is seeded with the defaults documented
in docs/rules/*.md. learned_rule is created here because the scanner must
CONSULT it from M4 on (writing to it is M10's job). decision/suppression_hit
follow in M10.

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-02
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM, JSONB

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

register_enum = ENUM("analiza", "preporuka", "akcija", name="register", create_type=False)
conf_band_enum = ENUM("niska", "srednja", "visoka", name="conf_band", create_type=False)
signal_status_enum = ENUM(
    "new", "tasked", "dismissed", "suppressed", "resolved", name="signal_status", create_type=False
)
lr_status_enum = ENUM(
    "pending_confirm", "active", "reverted", "expired", name="lr_status", create_type=False
)
autonomy_enum = ENUM("auto_applied", "confirmed", name="autonomy", create_type=False)


# Default thresholds (documented in docs/rules/*.md). Values are JSONB.
DEFAULT_RULE_CONFIG: list[tuple[str, str, object]] = [
    # global confidence bands + cap
    ("global", "conf_band_high", 0.75),
    ("global", "conf_band_mid", 0.50),
    ("global", "conf_cap", 0.95),
    # customer_decline
    ("customer_decline", "decline_ratio_threshold", 0.65),
    ("customer_decline", "min_baseline_60d", 500),
    ("customer_decline", "seasonal_yoy_tolerance", 0.75),
    ("customer_decline", "conf_at_threshold", 0.40),
    ("customer_decline", "conf_at_floor", 0.90),
    ("customer_decline", "conf_floor_ratio", 0.35),
    # lost_article
    ("lost_article", "gap_factor", 3.0),
    ("lost_article", "min_purchases", 4),
    ("lost_article", "min_avg_interval_d", 5),
    ("lost_article", "conf_at_gap_factor", 0.50),
    ("lost_article", "conf_per_extra_gap", 0.10),
    # lost_category
    ("lost_category", "gap_days", 90),
    ("lost_category", "min_purchases", 5),
    ("lost_category", "conf_base", 0.50),
    ("lost_category", "conf_per_30d", 0.10),
    # sleeping_customer
    ("sleeping_customer", "gap_factor", 3.0),
    ("sleeping_customer", "min_gap_days", 60),
    ("sleeping_customer", "min_history_orders", 10),
    ("sleeping_customer", "conf_at_min", 0.50),
    ("sleeping_customer", "conf_per_extra_gap", 0.10),
    # narrow_basket
    ("narrow_basket", "max_categories", 2),
    ("narrow_basket", "min_peer_prevalence", 0.60),
    ("narrow_basket", "min_baseline_60d", 300),
]


def upgrade() -> None:
    # ── enums (shared by app.* tables from here on) ───────────────────────────
    for enum in (register_enum, conf_band_enum, signal_status_enum, lr_status_enum, autonomy_enum):
        enum.create(op.get_bind(), checkfirst=True)

    # ── app.rule_config: every detection threshold lives here ────────────────
    op.create_table(
        "rule_config",
        sa.Column("rule", sa.Text(), primary_key=True),
        sa.Column("param", sa.Text(), primary_key=True),
        sa.Column("value", JSONB(), nullable=False),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="app",
    )

    # ── app.signal ────────────────────────────────────────────────────────────
    op.create_table(
        "signal",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("rule", sa.Text(), nullable=False),
        sa.Column("customer_id", sa.BigInteger(), sa.ForeignKey("core.customer.id")),
        sa.Column("article_id", sa.BigInteger(), sa.ForeignKey("core.article.id")),
        sa.Column("evidence", JSONB(), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("conf_band", conf_band_enum, nullable=False),
        sa.Column("register", register_enum, nullable=False, server_default=sa.text("'analiza'")),
        sa.Column("status", signal_status_enum, nullable=False, server_default=sa.text("'new'")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="app",
    )
    op.create_index("ix_signal_status", "signal", ["status"], schema="app")
    op.create_index("ix_signal_customer", "signal", ["customer_id"], schema="app")

    # ── app.learned_rule (consulted by the scanner from M4; written in M10) ──
    op.create_table(
        "learned_rule",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("source_signal_id", sa.BigInteger(), sa.ForeignKey("app.signal.id")),
        sa.Column("source_message_id", sa.BigInteger(), nullable=True),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("rule_type", sa.Text(), nullable=False),
        sa.Column("scope", JSONB(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("effect_estimate", JSONB(), nullable=True),
        sa.Column("status", lr_status_enum, nullable=False, server_default=sa.text("'active'")),
        sa.Column("autonomy", autonomy_enum, nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        schema="app",
    )
    op.create_index(
        "ix_learned_rule_active",
        "learned_rule",
        ["status"],
        schema="app",
        postgresql_where=sa.text("status = 'active'"),
    )

    # ── seed the default thresholds ───────────────────────────────────────────
    connection = op.get_bind()
    for rule, param, value in DEFAULT_RULE_CONFIG:
        connection.execute(
            sa.text(
                "INSERT INTO app.rule_config (rule, param, value) "
                "VALUES (:rule, :param, CAST(:value AS jsonb))"
            ),
            {"rule": rule, "param": param, "value": json.dumps(value)},
        )


def downgrade() -> None:
    op.drop_table("learned_rule", schema="app")
    op.drop_table("signal", schema="app")
    op.drop_table("rule_config", schema="app")
    for enum in (autonomy_enum, lr_status_enum, signal_status_enum, conf_band_enum, register_enum):
        enum.drop(op.get_bind(), checkfirst=True)
