"""LLM router: route log + routing thresholds (M12).

audit.llm_route_log exactly per docs/data-model.md (one append-only row per routing
decision), plus the role→tier mapping and cascade thresholds seeded into
app.rule_config (CLAUDE.md: thresholds in DB, never hard-coded).

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-03
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Spec D2/D3: role→tier defaults (60-70% Haiku by construction — every high/medium
# volume role is tier1; only the weekly audit and future investigations go higher)
# + the cascade policy.
ROUTER_DEFAULTS = {
    "role_tiers": {
        "narration": "tier1",
        "intent": "tier1",
        "simple_qa": "tier1",
        "nl_rule": "tier1",
        "report_narration": "tier1",
        "customer_draft": "tier1",
        "over_suppression_audit": "tier2",
        "investigation": "tier2",
        "investigation_synthesis": "tier2_strong",
    },
    "escalation_confidence_threshold": 0.6,
    "cascade_enabled": True,
    "cascade_max_escalations": 1,
}


def upgrade() -> None:
    # ── audit.llm_route_log (APPEND-ONLY) ─────────────────────────────────────
    op.create_table(
        "llm_route_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("request_id", sa.Text()),
        sa.Column("task_role", sa.Text()),
        sa.Column("chosen_tier", sa.Text()),
        sa.Column("model", sa.Text()),
        sa.Column("reason", sa.Text()),
        sa.Column("confidence", sa.Numeric(4, 3)),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="audit",
    )
    op.create_index("ix_llm_route_log_role", "llm_route_log", ["task_role"], schema="audit")

    # ── llm_router thresholds → app.rule_config ──────────────────────────────
    connection = op.get_bind()
    for param, value in ROUTER_DEFAULTS.items():
        connection.execute(
            sa.text(
                "INSERT INTO app.rule_config (rule, param, value) "
                "VALUES ('llm_router', :param, CAST(:value AS jsonb)) "
                "ON CONFLICT (rule, param) DO NOTHING"
            ),
            {"param": param, "value": json.dumps(value)},
        )


def downgrade() -> None:
    op.get_bind().execute(sa.text("DELETE FROM app.rule_config WHERE rule = 'llm_router'"))
    op.drop_index("ix_llm_route_log_role", "llm_route_log", schema="audit")
    op.drop_table("llm_route_log", schema="audit")
