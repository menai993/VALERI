"""Seed chat-agent loop caps (CSA Phase 2).

The synchronous in-chat plan→act→synthesize loop is bounded by caps in
app.rule_config (thresholds live in the DB, never hard-coded). Small,
chat-appropriate values keep latency/cost low; the deep async investigation
agent keeps its own larger 'investigation' caps.

Revision ID: 0021
Revises: 0020
Create Date: 2026-06-03
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHAT_AGENT_CAPS = {
    "max_steps": 4,  # at most 4 tool calls per question
    "max_seconds": 30,  # wall-clock bound on the synchronous loop
}


def upgrade() -> None:
    connection = op.get_bind()
    for param, value in CHAT_AGENT_CAPS.items():
        connection.execute(
            sa.text(
                "INSERT INTO app.rule_config (rule, param, value) "
                "VALUES ('chat_agent', :param, CAST(:value AS jsonb)) "
                "ON CONFLICT (rule, param) DO NOTHING"
            ),
            {"param": param, "value": json.dumps(value)},
        )


def downgrade() -> None:
    op.get_bind().execute(sa.text("DELETE FROM app.rule_config WHERE rule = 'chat_agent'"))
