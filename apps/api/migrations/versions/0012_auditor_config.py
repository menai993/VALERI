"""Over-suppression auditor thresholds (M11).

Seed-only migration — no schema changes. The drift/volume thresholds the auditor
uses live in app.rule_config (CLAUDE.md: thresholds in DB, never hard-coded).

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-03
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Spec D1: value drift = current/baseline ratio at or below audit_drift_factor;
# volume drift = actual hits >= audit_volume_factor x predicted effect.
# Rules with fewer than audit_min_hits hits are not audited yet (too little data).
AUDITOR_DEFAULTS = {
    "audit_drift_factor": 0.7,
    "audit_volume_factor": 3,
    "audit_min_hits": 2,
}


def upgrade() -> None:
    connection = op.get_bind()
    for param, value in AUDITOR_DEFAULTS.items():
        connection.execute(
            sa.text(
                "INSERT INTO app.rule_config (rule, param, value) "
                "VALUES ('selfconfig', :param, CAST(:value AS jsonb)) "
                "ON CONFLICT (rule, param) DO NOTHING"
            ),
            {"param": param, "value": json.dumps(value)},
        )


def downgrade() -> None:
    connection = op.get_bind()
    for param in AUDITOR_DEFAULTS:
        connection.execute(
            sa.text("DELETE FROM app.rule_config WHERE rule = 'selfconfig' AND param = :param"),
            {"param": param},
        )
