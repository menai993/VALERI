"""P3 LLM cost tracking: ai_log cost columns + pricing + budget.

Turns audit.ai_log into a cost ledger (feature/user/tier/token splits/cost_usd,
computed at write time from DB-seeded prices) and adds app.llm_pricing +
app.llm_budget. Prices are DB rows (never hard-coded in app code) and editable
via the admin API — seeded here from current Anthropic pricing. Per-feature caps
and the throttle threshold live in app.rule_config (rule 'llm_cost').

audit.ai_log stays APPEND-ONLY — these are additive columns, no update path.

Revision ID: 0025
Revises: 0024
Create Date: 2026-06-11
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# USD per 1M tokens, confirmed against current Anthropic pricing (docs.claude.com,
# 2026-06). DB rows, not literals in app code — the admin can edit them any time.
# Keyed by BOTH the Claude model id and the LiteLLM tier alias, because the gateway
# may echo either form back in the response.
_PRICING = [
    # (model, input_per_mtok, output_per_mtok, cache_read_per_mtok)
    ("claude-haiku-4-5-20251001", "1.00", "5.00", "0.10"),
    ("claude-haiku-4-5", "1.00", "5.00", "0.10"),
    ("tier1", "1.00", "5.00", "0.10"),
    ("claude-sonnet-4-6", "3.00", "15.00", "0.30"),
    ("tier2", "3.00", "15.00", "0.30"),
    ("claude-opus-4-8", "5.00", "25.00", "0.50"),
    ("tier2_strong", "5.00", "25.00", "0.50"),
]

# Per-feature daily caps + the near-cap throttle (D7). Non-essential roles defer
# when month spend crosses throttle_pct of the budget (chat is never throttled).
_LLM_COST_THRESHOLDS = {
    "feature_daily_caps": {"investigation": 10},
    "throttle_pct": 90,
    "non_essential_roles": [
        "report_narration",
        "customer_draft",
        "over_suppression_audit",
        "kb_summary",
    ],
}


def upgrade() -> None:
    # ── audit.ai_log cost-attribution columns (additive, append-only stays) ──
    op.add_column("ai_log", sa.Column("feature", sa.Text()), schema="audit")
    op.add_column("ai_log", sa.Column("user_id", sa.BigInteger()), schema="audit")
    op.add_column("ai_log", sa.Column("tier", sa.Text()), schema="audit")
    op.add_column("ai_log", sa.Column("input_tokens", sa.Integer()), schema="audit")
    op.add_column("ai_log", sa.Column("output_tokens", sa.Integer()), schema="audit")
    op.add_column(
        "ai_log",
        sa.Column("cached", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema="audit",
    )
    op.add_column("ai_log", sa.Column("cached_input_tokens", sa.Integer()), schema="audit")
    op.add_column(
        "ai_log",
        sa.Column("batched", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema="audit",
    )
    op.add_column("ai_log", sa.Column("cost_usd", sa.Numeric(12, 6)), schema="audit")
    op.create_index(
        "ix_ai_log_feature_created", "ai_log", ["feature", "created_at"], schema="audit"
    )

    # ── app.llm_pricing ──────────────────────────────────────────────────────
    op.create_table(
        "llm_pricing",
        sa.Column("model", sa.Text(), primary_key=True),
        sa.Column("input_per_mtok", sa.Numeric(10, 4), nullable=False),
        sa.Column("output_per_mtok", sa.Numeric(10, 4), nullable=False),
        sa.Column("cache_read_per_mtok", sa.Numeric(10, 4)),
        sa.Column(
            "batch_discount", sa.Numeric(4, 3), nullable=False, server_default=sa.text("0.5")
        ),
        sa.Column(
            "effective_date", sa.Date(), nullable=False, server_default=sa.func.current_date()
        ),
        schema="app",
    )

    # ── app.llm_budget (the 'default' row makes alerting work without monthly chores) ──
    op.create_table(
        "llm_budget",
        sa.Column("period", sa.Text(), primary_key=True),  # 'YYYY-MM' or 'default'
        sa.Column("limit_usd", sa.Numeric(12, 2), nullable=False),
        sa.Column("alert_pct", sa.Integer(), nullable=False, server_default=sa.text("80")),
        schema="app",
    )

    bind = op.get_bind()
    for model, input_p, output_p, cache_p in _PRICING:
        bind.execute(
            sa.text(
                "INSERT INTO app.llm_pricing "
                "(model, input_per_mtok, output_per_mtok, cache_read_per_mtok) "
                "VALUES (:m, :i, :o, :c) ON CONFLICT (model) DO NOTHING"
            ),
            {"m": model, "i": input_p, "o": output_p, "c": cache_p},
        )
    bind.execute(
        sa.text(
            "INSERT INTO app.llm_budget (period, limit_usd, alert_pct) "
            "VALUES ('default', 50, 80) ON CONFLICT (period) DO NOTHING"
        )
    )
    for param, value in _LLM_COST_THRESHOLDS.items():
        bind.execute(
            sa.text(
                "INSERT INTO app.rule_config (rule, param, value) "
                "VALUES ('llm_cost', :param, CAST(:value AS jsonb)) "
                "ON CONFLICT (rule, param) DO NOTHING"
            ),
            {"param": param, "value": json.dumps(value)},
        )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM app.rule_config WHERE rule = 'llm_cost'"))
    op.drop_table("llm_budget", schema="app")
    op.drop_table("llm_pricing", schema="app")
    op.drop_index("ix_ai_log_feature_created", "ai_log", schema="audit")
    for col in (
        "cost_usd",
        "batched",
        "cached_input_tokens",
        "cached",
        "output_tokens",
        "input_tokens",
        "tier",
        "user_id",
        "feature",
    ):
        op.drop_column("ai_log", col, schema="audit")
