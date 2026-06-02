"""Create the staging / core / app / audit schemas.

M0: no tables yet — only the four PostgreSQL schemas that the data model
(docs/data-model.md) builds on from M1 onward.

Revision ID: 0001
Revises:
Create Date: 2026-06-02
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMAS = ("staging", "core", "app", "audit")


def upgrade() -> None:
    for schema in SCHEMAS:
        op.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')


def downgrade() -> None:
    for schema in reversed(SCHEMAS):
        op.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
