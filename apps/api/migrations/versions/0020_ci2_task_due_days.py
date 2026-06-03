"""Seed task_due_days for the CI2 graph-aware rules.

CI2 added three detection rules (group_risk, behavioral_twin_warning,
referral_source_risk) to the scanner and seeded their detection thresholds, but
NOT their per-rule task_due_days. The M5 task pipeline fails loudly when a
signal's rule has no task_due_days entry (thresholds live in the DB, never
hard-coded), so any signal from these rules aborted the whole scan→task
transaction. This seeds the missing entries so tasks are created for them.

Revision ID: 0020
Revises: 0019
Create Date: 2026-06-03
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Due-date windows per CI2 rule (mirrors the M5 defaults: risk → short window).
TASK_DUE_DAYS = {
    "group_risk": 3,
    "behavioral_twin_warning": 5,
    "referral_source_risk": 7,
}


def upgrade() -> None:
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
    op.get_bind().execute(
        sa.text(
            "DELETE FROM app.rule_config WHERE param = 'task_due_days' "
            "AND rule IN ('group_risk', 'behavioral_twin_warning', 'referral_source_risk')"
        )
    )
