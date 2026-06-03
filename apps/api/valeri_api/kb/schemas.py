"""Pydantic schemas for the knowledge base (CI1).

Two families:
  • LLM output schemas (RelevanceDecision, ExtractionResult + candidates) — parsed
    via narrate_structured, malformed output rejected+retried, never shown raw.
  • Server-side / API schemas (resolution, capture/pending/knowledge responses).

The LLM emits qualitative candidates with a STATED value tagged source='stated';
numbers for analysis come from SQL. Entity ids are never produced by the model —
resolution maps mentioned names to ids server-side.
"""

import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from valeri_api.kb.models import CLAR_KINDS, EVENT_KINDS, FACT_SOURCES, REL_TYPES

Register = Literal["analiza", "preporuka", "akcija"]
FactSource = Literal["data", "inferred", "stated"]
Stakes = Literal["low", "high"]

# Literals derived from the enum tuples (kept in sync with kb.models).
EventKind = Literal[*EVENT_KINDS]
RelType = Literal[*REL_TYPES]
ClarKind = Literal[*CLAR_KINDS]

assert set(FACT_SOURCES) == {"data", "inferred", "stated"}  # guard the Literal above


# ── LLM output: relevance gate ──────────────────────────────────────────────────


class RelevanceDecision(BaseModel):
    """The Tier-1 gate: does this message assert something worth capturing?"""

    relevant: bool


# ── LLM output: extraction candidates ───────────────────────────────────────────


class ExtractedFact(BaseModel):
    """One qualitative fact candidate. `value` is structured, never a computed number."""

    fact_type: str = Field(min_length=1, max_length=60)
    fact_key: str = Field(min_length=1, max_length=120)
    value: dict[str, Any]
    mentioned_name: str | None = None  # the customer as named; None → the focus customer
    source: FactSource = "stated"
    stakes: Stakes = "low"
    confidence: float = Field(ge=0, le=1)
    evidence_span: str = Field(min_length=1)

    @field_validator("value", mode="before")
    @classmethod
    def _wrap_scalar_value(cls, value: Any) -> Any:
        """Tolerate a scalar the model occasionally emits → wrap it, don't reject.

        The prompt asks for a JSON object; an odd attempt may send a string. Wrapping
        keeps capture on Haiku (attempt 1) instead of failing and cascading to Tier-2.
        """
        return value if isinstance(value, dict) else {"value": value}


class ExtractedEvent(BaseModel):
    """One commercial-event candidate (deal/meeting/complaint/…); STATED value is data."""

    kind: EventKind
    summary: str = Field(min_length=1)
    mentioned_name: str | None = None
    value: float | None = Field(default=None, ge=0)  # STATED, stored tagged source='stated'
    categories: list[str] = []
    occurred_on: datetime.date | None = None
    source: FactSource = "stated"
    confidence: float = Field(ge=0, le=1)
    evidence_span: str = Field(min_length=1)


class ExtractedRelationship(BaseModel):
    """One customer↔customer edge candidate. Consequential → confirmation queue."""

    rel_type: RelType
    to_name: str = Field(min_length=1)
    from_name: str | None = None  # None → the focus customer
    source: FactSource = "stated"
    confidence: float = Field(ge=0, le=1)
    evidence_span: str = Field(min_length=1)


class ExtractionResult(BaseModel):
    """Everything one extraction pass produced from a single utterance."""

    facts: list[ExtractedFact] = []
    events: list[ExtractedEvent] = []
    relationships: list[ExtractedRelationship] = []
    confidence: float = Field(ge=0, le=1)  # overall pass confidence (logged to kb_extraction)


# ── server-side entity resolution (deterministic, never the model) ──────────────


class ResolutionCandidate(BaseModel):
    """One ranked match for a mentioned name, with a distinguishing detail."""

    customer_id: int
    name: str
    similarity: float
    segment: str | None = None
    last_order: datetime.date | None = None


class ResolutionResult(BaseModel):
    """The outcome of resolving one mentioned name (§8.2 decision matrix)."""

    mentioned_name: str
    candidates: list[ResolutionCandidate] = []
    decision: Literal["auto", "clarify", "none"]
    customer_id: int | None = None  # set iff decision == 'auto'
    reason: str | None = None


# ── API request bodies ──────────────────────────────────────────────────────────


class CaptureRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    customer_id: int | None = None  # current customer focus, if any


class NoteCreate(BaseModel):
    customer_id: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=4000)


class ItemEdit(BaseModel):
    """PATCH /kb/items/{id}: edit a record's editable fields (writes a decision)."""

    item_type: Literal["fact", "event", "relationship"]
    customer_id: int | None = None
    value: dict[str, Any] | None = None
    summary: str | None = None
    fact_key: str | None = None


class ClarificationAnswer(BaseModel):
    """POST /kb/clarifications/{id}/answer: the chosen tappable option."""

    option: dict[str, Any]  # {action: 'link'|'pick_other'|'create_prospect'|..., customer_id?: int}


# ── API read shapes ─────────────────────────────────────────────────────────────


class KbItemRead(BaseModel):
    """A fact or event, for the knowledge panel / review queue (each carries the envelope)."""

    item_type: Literal["fact", "event"]
    id: int
    customer_id: int | None
    customer_name: str | None
    mentioned_name: str | None = None
    title: str  # fact_type:fact_key, or event summary
    detail: dict[str, Any] | None = None  # fact value / event fields
    register: Register
    source: FactSource
    confidence: str
    conf_band: str
    status: str
    evidence_text: str | None
    source_message_id: int | None
    created_at: datetime.datetime


class RelationshipRead(BaseModel):
    item_type: Literal["relationship"] = "relationship"
    id: int
    from_customer_id: int
    from_name: str | None
    to_customer_id: int
    to_name: str | None
    rel_type: str
    register: Register
    source: FactSource
    confidence: str
    conf_band: str
    status: str
    evidence_text: str | None
    created_at: datetime.datetime


class ClarificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: ClarKind
    question: str
    options: list[dict[str, Any]]
    target_record_ref: str
    status: str
    created_at: datetime.datetime


class ProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    customer_id: int
    summary: str | None
    decision_maker: str | None
    preferences: dict[str, Any] | None
    updated_at: datetime.datetime


class CaptureResponse(BaseModel):
    """What POST /kb/capture (and the chat hook, internally) produced."""

    auto_saved: list[KbItemRead | RelationshipRead] = []
    proposed: list[KbItemRead | RelationshipRead] = []
    clarifications: list[ClarificationRead] = []


class PendingQueue(BaseModel):
    """GET /kb/pending: proposed records + pending clarifications, each with its source."""

    facts: list[KbItemRead] = []
    events: list[KbItemRead] = []
    relationships: list[RelationshipRead] = []
    clarifications: list[ClarificationRead] = []


class KnowledgeResponse(BaseModel):
    """GET /customers/{id}/knowledge: profile + active facts + events + relationships."""

    profile: ProfileRead | None
    facts: list[KbItemRead] = []
    events: list[KbItemRead] = []
    relationships: list[RelationshipRead] = []
