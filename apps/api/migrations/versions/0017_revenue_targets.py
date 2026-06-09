"""Phase-2 CRM: revenue targets / plan (C-CRM2).

app.revenue_target holds the company's monthly revenue plan ('YYYY-MM' → amount),
used for revenue-vs-plan and the run-rate forecast. No LLM; the ERP stays read-only;
app.activity already exists (created in C-CRM1) and is used, not created, here.

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "revenue_target",
        # period is the natural key: 'YYYY-MM' (company monthly plan).
        sa.Column("period", sa.Text(), primary_key=True),
        sa.Column("target_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="app",
    )


def downgrade() -> None:
    op.drop_table("revenue_target", schema="app")
