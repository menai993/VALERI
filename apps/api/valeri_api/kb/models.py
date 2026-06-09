"""SQLAlchemy models for the Client Intelligence knowledge base (CI1).

The KB tables per docs/client-intelligence.md §2 + §8.4: client_profile,
client_fact, commercial_event, client_relationship, kb_extraction, plus
customer_alias and clarification. These hold qualitative knowledge captured
from what users say — every record carries provenance (source message/user),
confidence, and the raw utterance as evidence. Numbers for analysis stay in
SQL; the LLM only extracts/narrates into these typed rows.

Additive columns beyond the illustrative DDL: `mentioned_name` (the name as
spoken, kept when a mention is unresolved) and `evidence_text` (the source
sentence/span) — so a record is traceable even for notes that have no
app.message row.
"""

import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Numeric, Text, func
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from valeri_api.db import Base

# ── enums (created in migration 0018; conf_band already exists from M4) ─────────

FACT_SOURCES = ("data", "inferred", "stated")
KB_STATUSES = ("proposed", "active", "superseded", "rejected")
EVENT_KINDS = ("deal", "meeting", "call", "complaint", "quote", "visit", "note", "other")
REL_TYPES = (
    "same_owner",
    "same_group",
    "chain",
    "shared_decision_maker",
    "referral",
    "competitor",
    "geographic_cluster",
    "behavioral_twin",
    "supplier_of",
)
CLAR_KINDS = ("entity", "reference", "merge", "value", "conflict", "new_entity")

fact_source_enum = ENUM(*FACT_SOURCES, name="fact_source", create_type=False)
kb_status_enum = ENUM(*KB_STATUSES, name="kb_status", create_type=False)
event_kind_enum = ENUM(*EVENT_KINDS, name="event_kind", create_type=False)
rel_type_enum = ENUM(*REL_TYPES, name="rel_type", create_type=False)
clar_kind_enum = ENUM(*CLAR_KINDS, name="clar_kind", create_type=False)
conf_band_enum = ENUM("niska", "srednja", "visoka", name="conf_band", create_type=False)


# ── living per-customer rollup ──────────────────────────────────────────────────


class ClientProfile(Base):
    """One LLM-maintained narrative summary per customer (Bosnian)."""

    __tablename__ = "client_profile"
    __table_args__ = {"schema": "app"}

    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("core.customer.id"), primary_key=True
    )
    summary: Mapped[str | None] = mapped_column(Text)
    decision_maker: Mapped[str | None] = mapped_column(Text)
    preferences: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# ── atomic qualitative facts ────────────────────────────────────────────────────


class ClientFact(Base):
    """One qualitative fact; dedup by (customer_id, fact_type, fact_key) among active."""

    __tablename__ = "client_fact"
    __table_args__ = {"schema": "app"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # NULL while a mention is unresolved (e.g. the Fupupu clarification case).
    customer_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("core.customer.id"))
    mentioned_name: Mapped[str | None] = mapped_column(Text)
    fact_type: Mapped[str] = mapped_column(Text, nullable=False)
    fact_key: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source: Mapped[str] = mapped_column(fact_source_enum, nullable=False)
    source_message_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app.message.id"))
    source_user_id: Mapped[int | None] = mapped_column(BigInteger)
    evidence_text: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    conf_band: Mapped[str] = mapped_column(conf_band_enum, nullable=False)
    status: Mapped[str] = mapped_column(kb_status_enum, nullable=False, server_default="active")
    superseded_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app.client_fact.id"))
    valid_from: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# ── captured events (deal / meeting / complaint / quote / …) ────────────────────


class CommercialEvent(Base):
    """A captured event; STATED value stored as data, tagged source='stated'."""

    __tablename__ = "commercial_event"
    __table_args__ = {"schema": "app"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    customer_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("core.customer.id"))
    mentioned_name: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(event_kind_enum, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    categories: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    occurred_on: Mapped[datetime.date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(fact_source_enum, nullable=False, server_default="stated")
    source_message_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app.message.id"))
    source_user_id: Mapped[int | None] = mapped_column(BigInteger)
    evidence_text: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    conf_band: Mapped[str] = mapped_column(conf_band_enum, nullable=False)
    status: Mapped[str] = mapped_column(kb_status_enum, nullable=False, server_default="active")
    # Optional link if the Phase-2 CRM track is on (no FK — CRM is optional). Unused in CI1.
    opportunity_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# ── the connect-the-dots graph ──────────────────────────────────────────────────


class ClientRelationship(Base):
    """A customer↔customer edge; consequential edges start 'proposed' (await confirm)."""

    __tablename__ = "client_relationship"
    __table_args__ = {"schema": "app"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    from_customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("core.customer.id"), nullable=False
    )
    to_customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("core.customer.id"), nullable=False
    )
    rel_type: Mapped[str] = mapped_column(rel_type_enum, nullable=False)
    source: Mapped[str] = mapped_column(fact_source_enum, nullable=False)
    source_message_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app.message.id"))
    source_user_id: Mapped[int | None] = mapped_column(BigInteger)
    evidence_text: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    conf_band: Mapped[str] = mapped_column(conf_band_enum, nullable=False)
    status: Mapped[str] = mapped_column(kb_status_enum, nullable=False, server_default="proposed")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# ── provenance / debug: one row per extraction pass ─────────────────────────────


class KBExtraction(Base):
    """The candidates an extraction pass produced, before apply (provenance/debug)."""

    __tablename__ = "kb_extraction"
    __table_args__ = {"schema": "app"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    message_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app.message.id"))
    raw_text: Mapped[str | None] = mapped_column(Text)
    extracted: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    model: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# ── learned aliases + clarification questions (§8.4) ────────────────────────────


class CustomerAlias(Base):
    """A confirmed nickname/misspelling → first-class alias (mirrors article_alias)."""

    __tablename__ = "customer_alias"
    __table_args__ = {"schema": "app"}

    alias: Mapped[str] = mapped_column(Text, primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("core.customer.id"), nullable=False
    )
    source: Mapped[str] = mapped_column(fact_source_enum, nullable=False, server_default="stated")
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Clarification(Base):
    """One short question raised when a capture is ambiguous or high-stakes (§8.3)."""

    __tablename__ = "clarification"
    __table_args__ = {"schema": "app"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(clar_kind_enum, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    target_record_ref: Mapped[str] = mapped_column(Text, nullable=False)  # e.g. "client_fact:123"
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    answer: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    answered_by: Mapped[int | None] = mapped_column(BigInteger)
    answered_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
