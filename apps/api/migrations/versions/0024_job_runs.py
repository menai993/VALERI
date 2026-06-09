"""P2 ops hardening: the job-run ledger + ops thresholds.

app.job_run records every scheduled-job execution (scan, weekly cycle, audit,
backup restore-check) plus a single worker-heartbeat row. It is OPERATIONAL
TELEMETRY — prunable (90-day retention in the weekly job) and deliberately
distinct from the append-only audit family (audit.*, app.decision).

Thresholds live in app.rule_config (rule 'ops'), never code.

Revision ID: 0024
Revises: 0023
Create Date: 2026-06-09
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Spec D-defaults: alerting thresholds (tunable in app.rule_config).
OPS_THRESHOLDS = {
    "alert_consecutive_failures": 2,  # a job failing this many times in a row alerts
    "scan_stale_days": 7,  # newest invoice older than this → scan skips + alerts
    "restore_check_max_age_days": 8,  # last ok restore-check older than this → alert
}


def upgrade() -> None:
    op.create_table(
        "job_run",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("job", sa.Text(), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.Text(), nullable=False, server_default="running"),
        sa.Column("error", sa.Text()),
        sa.Column("detail", JSONB()),
        schema="app",
    )
    op.create_index("ix_job_run_job_id", "job_run", ["job", sa.text("id DESC")], schema="app")

    bind = op.get_bind()
    for param, value in OPS_THRESHOLDS.items():
        bind.execute(
            sa.text(
                "INSERT INTO app.rule_config (rule, param, value) "
                "VALUES ('ops', :param, CAST(:value AS jsonb)) "
                "ON CONFLICT (rule, param) DO NOTHING"
            ),
            {"param": param, "value": json.dumps(value)},
        )


def downgrade() -> None:
    op.get_bind().execute(sa.text("DELETE FROM app.rule_config WHERE rule = 'ops'"))
    op.drop_index("ix_job_run_job_id", "job_run", schema="app")
    op.drop_table("job_run", schema="app")
