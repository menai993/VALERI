"""Client Intelligence CI1: the conversational knowledge base.

Adds the KB tables per docs/client-intelligence.md §2 + §8.4 (client_profile,
client_fact, commercial_event, client_relationship, kb_extraction, customer_alias,
clarification) and their enums; enables pg_trgm + a trigram index on
core.customer(name) for fuzzy entity resolution; extends decision_kind with
'kb_capture' (auto-saved KB writes are reversible, logged decisions); and seeds
the kb.* thresholds in app.rule_config (never hard-coded).

No ERP writes — the KB is VALERI-native qualitative knowledge with provenance.

Revision ID: 0018
Revises: 0017
Create Date: 2026-06-03
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM, JSONB

# revision identifiers, used by Alembic.
revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Spec D4: capture thresholds. Tunable in app.rule_config, never in code.
KB_THRESHOLDS = {
    "fact_autosave_confidence": 0.75,  # below → confirmation queue, never auto-save
    "auto_attach_similarity": 0.80,  # trgm similarity needed to auto-attach a mention
    "high_stakes_always_confirm": True,  # payment/negative/relationship/large value → confirm
    "high_stakes_value": 10000,  # a stated value at/above this is high-stakes
}

_NEW_ENUMS = {
    "fact_source": ("data", "inferred", "stated"),
    "kb_status": ("proposed", "active", "superseded", "rejected"),
    "event_kind": ("deal", "meeting", "call", "complaint", "quote", "visit", "note", "other"),
    "rel_type": (
        "same_owner",
        "same_group",
        "chain",
        "shared_decision_maker",
        "referral",
        "competitor",
        "geographic_cluster",
        "behavioral_twin",
        "supplier_of",
    ),
    "clar_kind": ("entity", "reference", "merge", "value", "conflict", "new_entity"),
}


def upgrade() -> None:
    bind = op.get_bind()

    # ── fuzzy-resolution support ──────────────────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # ── enums (conf_band already exists from M4) ──────────────────────────────
    for name, values in _NEW_ENUMS.items():
        labels = ", ".join(f"'{v}'" for v in values)
        op.execute(f"CREATE TYPE {name} AS ENUM ({labels})")
    # Auto-saved KB writes are reversible, logged decisions (kind='kb_capture').
    # ADD VALUE is allowed inside this transaction on PG12+; it is not USED here.
    op.execute("ALTER TYPE decision_kind ADD VALUE IF NOT EXISTS 'kb_capture'")

    fact_source = ENUM(name="fact_source", create_type=False)
    kb_status = ENUM(name="kb_status", create_type=False)
    event_kind = ENUM(name="event_kind", create_type=False)
    rel_type = ENUM(name="rel_type", create_type=False)
    clar_kind = ENUM(name="clar_kind", create_type=False)
    conf_band = ENUM(name="conf_band", create_type=False)

    # ── app.client_profile ────────────────────────────────────────────────────
    op.create_table(
        "client_profile",
        sa.Column(
            "customer_id",
            sa.BigInteger(),
            sa.ForeignKey("core.customer.id"),
            primary_key=True,
        ),
        sa.Column("summary", sa.Text()),
        sa.Column("decision_maker", sa.Text()),
        sa.Column("preferences", JSONB()),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        schema="app",
    )

    # ── app.client_fact ───────────────────────────────────────────────────────
    op.create_table(
        "client_fact",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("customer_id", sa.BigInteger(), sa.ForeignKey("core.customer.id")),
        sa.Column("mentioned_name", sa.Text()),
        sa.Column("fact_type", sa.Text(), nullable=False),
        sa.Column("fact_key", sa.Text(), nullable=False),
        sa.Column("value", JSONB(), nullable=False),
        sa.Column("source", fact_source, nullable=False),
        sa.Column("source_message_id", sa.BigInteger(), sa.ForeignKey("app.message.id")),
        sa.Column("source_user_id", sa.BigInteger()),
        sa.Column("evidence_text", sa.Text()),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("conf_band", conf_band, nullable=False),
        sa.Column("status", kb_status, nullable=False, server_default="active"),
        sa.Column("superseded_by", sa.BigInteger(), sa.ForeignKey("app.client_fact.id")),
        sa.Column(
            "valid_from", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        schema="app",
    )
    op.create_index(
        "ix_fact_customer_active",
        "client_fact",
        ["customer_id"],
        schema="app",
        postgresql_where=sa.text("status = 'active'"),
    )
    # At most one active fact per (customer, type, key) — merge supersedes the old.
    op.create_index(
        "ux_fact_active",
        "client_fact",
        ["customer_id", "fact_type", "fact_key"],
        unique=True,
        schema="app",
        postgresql_where=sa.text("status = 'active'"),
    )

    # ── app.commercial_event ──────────────────────────────────────────────────
    op.create_table(
        "commercial_event",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("customer_id", sa.BigInteger(), sa.ForeignKey("core.customer.id")),
        sa.Column("mentioned_name", sa.Text()),
        sa.Column("kind", event_kind, nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("value", sa.Numeric(14, 2)),
        sa.Column("categories", JSONB()),
        sa.Column("occurred_on", sa.Date()),
        sa.Column("source", fact_source, nullable=False, server_default="stated"),
        sa.Column("source_message_id", sa.BigInteger(), sa.ForeignKey("app.message.id")),
        sa.Column("source_user_id", sa.BigInteger()),
        sa.Column("evidence_text", sa.Text()),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("conf_band", conf_band, nullable=False),
        sa.Column("status", kb_status, nullable=False, server_default="active"),
        sa.Column("opportunity_id", sa.BigInteger()),  # optional Phase-2 link; no FK
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        schema="app",
    )
    op.create_index("ix_event_customer", "commercial_event", ["customer_id"], schema="app")

    # ── app.client_relationship ───────────────────────────────────────────────
    op.create_table(
        "client_relationship",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "from_customer_id", sa.BigInteger(), sa.ForeignKey("core.customer.id"), nullable=False
        ),
        sa.Column(
            "to_customer_id", sa.BigInteger(), sa.ForeignKey("core.customer.id"), nullable=False
        ),
        sa.Column("rel_type", rel_type, nullable=False),
        sa.Column("source", fact_source, nullable=False),
        sa.Column("source_message_id", sa.BigInteger(), sa.ForeignKey("app.message.id")),
        sa.Column("source_user_id", sa.BigInteger()),
        sa.Column("evidence_text", sa.Text()),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("conf_band", conf_band, nullable=False),
        sa.Column("status", kb_status, nullable=False, server_default="proposed"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        schema="app",
    )
    op.create_index("ix_rel_from", "client_relationship", ["from_customer_id"], schema="app")
    op.create_index("ix_rel_to", "client_relationship", ["to_customer_id"], schema="app")
    # Dedup by (from, to, rel_type) among non-rejected edges.
    op.create_index(
        "ux_rel_dedup",
        "client_relationship",
        ["from_customer_id", "to_customer_id", "rel_type"],
        unique=True,
        schema="app",
        postgresql_where=sa.text("status <> 'rejected'"),
    )

    # ── app.kb_extraction ─────────────────────────────────────────────────────
    op.create_table(
        "kb_extraction",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("message_id", sa.BigInteger(), sa.ForeignKey("app.message.id")),
        sa.Column("raw_text", sa.Text()),
        sa.Column("extracted", JSONB()),
        sa.Column("model", sa.Text()),
        sa.Column("confidence", sa.Numeric(4, 3)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        schema="app",
    )
    op.create_index("ix_kb_extraction_message", "kb_extraction", ["message_id"], schema="app")

    # ── app.customer_alias ────────────────────────────────────────────────────
    op.create_table(
        "customer_alias",
        sa.Column("alias", sa.Text(), primary_key=True),
        sa.Column(
            "customer_id", sa.BigInteger(), sa.ForeignKey("core.customer.id"), nullable=False
        ),
        sa.Column("source", fact_source, nullable=False, server_default="stated"),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        schema="app",
    )
    op.create_index("ix_customer_alias_customer", "customer_alias", ["customer_id"], schema="app")

    # ── app.clarification ─────────────────────────────────────────────────────
    op.create_table(
        "clarification",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("kind", clar_kind, nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("options", JSONB(), nullable=False),
        sa.Column("target_record_ref", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("answer", JSONB()),
        sa.Column("answered_by", sa.BigInteger()),
        sa.Column("answered_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        schema="app",
    )
    op.create_index(
        "ix_clarification_pending",
        "clarification",
        ["status"],
        schema="app",
        postgresql_where=sa.text("status = 'pending'"),
    )

    # ── trigram index for fuzzy customer-name resolution ──────────────────────
    op.execute("CREATE INDEX ix_customer_name_trgm ON core.customer USING gin (name gin_trgm_ops)")

    # ── kb.* thresholds → app.rule_config ─────────────────────────────────────
    for param, value in KB_THRESHOLDS.items():
        bind.execute(
            sa.text(
                "INSERT INTO app.rule_config (rule, param, value) "
                "VALUES ('kb', :param, CAST(:value AS jsonb)) "
                "ON CONFLICT (rule, param) DO NOTHING"
            ),
            {"param": param, "value": json.dumps(value)},
        )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM app.rule_config WHERE rule = 'kb'"))

    op.execute("DROP INDEX IF EXISTS core.ix_customer_name_trgm")

    op.drop_index("ix_clarification_pending", "clarification", schema="app")
    op.drop_table("clarification", schema="app")
    op.drop_index("ix_customer_alias_customer", "customer_alias", schema="app")
    op.drop_table("customer_alias", schema="app")
    op.drop_index("ix_kb_extraction_message", "kb_extraction", schema="app")
    op.drop_table("kb_extraction", schema="app")
    op.drop_index("ux_rel_dedup", "client_relationship", schema="app")
    op.drop_index("ix_rel_to", "client_relationship", schema="app")
    op.drop_index("ix_rel_from", "client_relationship", schema="app")
    op.drop_table("client_relationship", schema="app")
    op.drop_index("ix_event_customer", "commercial_event", schema="app")
    op.drop_table("commercial_event", schema="app")
    op.drop_index("ux_fact_active", "client_fact", schema="app")
    op.drop_index("ix_fact_customer_active", "client_fact", schema="app")
    op.drop_table("client_fact", schema="app")
    op.drop_table("client_profile", schema="app")

    for name in _NEW_ENUMS:
        op.execute(f"DROP TYPE IF EXISTS {name}")
    # The decision_kind 'kb_capture' value and the pg_trgm extension are left in
    # place (Postgres cannot cleanly drop an enum value; the extension may be shared).
