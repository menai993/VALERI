"""Pydantic schemas for the self-configuration loop (typed I/O per CLAUDE.md).

RuleChangeProposal is an LLM output schema — malformed output is rejected and
retried, never trusted. Everything the proposal references by entity is a
pseudonym; ids are resolved server-side.
"""

import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCOPE_KINDS = ("once", "entity", "category", "threshold", "conditional")


class ProposedScope(BaseModel):
    """The narrowest-fit scope the model proposes (data-model.md scope JSONB shape).

    entity_ref is a PSEUDONYM (Kupac-xxxxxx) — the proposer resolves it to a real
    entity_id server-side; the model never sees or invents real ids.
    """

    kind: Literal["once", "entity", "category", "threshold", "conditional"]
    rule: str | None = None  # which detection rule it applies to (None = all)
    entity_type: Literal["customer", "article"] | None = None
    entity_ref: str | None = None  # pseudonym, resolved server-side
    category: str | None = None  # segment / category name
    # threshold / conditional parameters:
    metric: str | None = None
    op: Literal[">", "<", ">=", "<="] | None = None
    value: float | None = None
    when: str | None = None  # e.g. "season=summer" (stored; evaluated M11+)


class RuleChangeProposal(BaseModel):
    """What Tier-1 produces from a dismissal reason (LLM output schema)."""

    rule_type: Literal["suppress", "threshold"]
    scope: ProposedScope
    description: str = Field(min_length=10)  # Bosnian, human-editable
    interpretation_confidence: float = Field(ge=0, le=1)


class EffectEstimate(BaseModel):
    """The SQL-computed blast radius of a scope."""

    window_days: int
    total_signals: int
    by_rule: dict[str, int]


class RuleChangeDraft(BaseModel):
    """A fully-resolved proposal: what the API returns and the applier consumes."""

    rule_type: str
    scope: dict[str, Any]  # resolved scope (real entity_id, no pseudonyms)
    description: str
    interpretation_confidence: float
    effect_estimate: EffectEstimate
    autonomy_decision: Literal["auto_apply", "requires_confirm"]
    source_signal_id: int | None = None
    source_message_id: int | None = None


# ── read schemas (API) ────────────────────────────────────────────────────────


class LearnedRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_signal_id: int | None
    source_message_id: int | None
    domain: str
    rule_type: str
    scope: dict[str, Any]
    description: str
    effect_estimate: dict[str, Any] | None
    status: str
    autonomy: str
    created_by: int | None
    created_at: datetime.datetime
    expires_at: datetime.datetime | None
    # SQL-computed actual effect (hit count), joined by the API:
    suppression_count: int = 0


class SuppressionHitRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    learned_rule_id: int
    signal_id: int | None
    suppressed_at: datetime.datetime


class DecisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    actor: str
    summary: str
    payload: dict[str, Any] | None
    reversible: bool
    reverted_decision_id: int | None
    created_at: datetime.datetime


# ── API request/response schemas ──────────────────────────────────────────────


class DismissRequest(BaseModel):
    reason_text: str = Field(min_length=3, max_length=1000)


class DismissResponse(BaseModel):
    """What a dismissal returns: the proposal + whether it already applied (D1)."""

    signal_id: int
    proposal: RuleChangeProposal
    effect_estimate: EffectEstimate
    requires_confirm: bool
    applied: bool
    learned_rule: LearnedRuleRead
    decision_id: int | None = None  # set when auto-applied
    register: Literal["preporuka", "akcija"]  # preporuka = pending, akcija = applied


class ApplyRequest(BaseModel):
    learned_rule_id: int


class ApplyResponse(BaseModel):
    learned_rule: LearnedRuleRead
    decision: DecisionRead
    register: Literal["akcija"] = "akcija"


class ScopePatchRequest(BaseModel):
    scope: dict[str, Any]


class LearnedRuleListResponse(BaseModel):
    items: list[LearnedRuleRead]


class LearnedRuleDetailResponse(BaseModel):
    rule: LearnedRuleRead
    hits: list[SuppressionHitRead]
    decisions: list[DecisionRead]


class DecisionListResponse(BaseModel):
    items: list[DecisionRead]
