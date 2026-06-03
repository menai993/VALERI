"""Pydantic/typed schemas for the investigation agent (typed I/O per CLAUDE.md).

The graph state is a plain TypedDict of JSON-serializable values — it is what the
LangGraph Postgres checkpointer persists, so a restarted process can resume. The
LLM output schemas are the ONLY shapes agent model calls may produce; malformed
output is rejected and retried, never trusted.
"""

import datetime
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

# ── the graph state (checkpointed; must stay JSON-serializable) ───────────────


class InvestigationState(TypedDict, total=False):
    investigation_id: int
    user_id: int
    question_masked: str
    # Masking survives restarts: pseudonym → real name / id maps live in state.
    pseudonyms: dict[str, str]
    pseudonym_ids: dict[str, int]
    # plan
    plan: list[str]
    # act loop accounting (budget caps are checked against these)
    act_count: int
    tokens_used: int
    started_ts: float
    # accumulated (masked) tool results: [{tool, params, output, ok, error}]
    tool_results: list[dict]
    # actions the model PROPOSED but may never execute itself (HITL-gated)
    proposed_actions: list[dict]
    critic_verdict: str | None
    budget_exhausted: str | None
    # set by POST /resume — read by execute_action
    hitl_decision: str | None
    failure: str | None
    # the synthesize node's output — the runner persists it to app.investigation.report
    report: dict | None


# ── LLM output schemas (Tier-2 / Tier-2-strong) ───────────────────────────────


class PlanOutput(BaseModel):
    """The plan node's output: the question decomposed into concrete sub-questions."""

    sub_questions: list[str] = Field(min_length=1, max_length=6)
    reasoning: str = Field(min_length=10)


class ToolChoice(BaseModel):
    """One act step: a read-only tool call, a gated action proposal, or 'I have enough'."""

    tool: str | None = None
    params: dict[str, Any] = {}
    reasoning: str = Field(min_length=5)
    # True → the tool is a mutation (create_task_draft); it goes to proposed_actions
    # and is NEVER dispatched by the act node.
    is_action_proposal: bool = False
    # True → the model says it has enough data (no tool call this step).
    done: bool = False


class CriticVerdict(BaseModel):
    """The critic's check: are the findings sufficient and grounded?"""

    verdict: Literal["dovoljno", "treba_jos"]
    reasoning: str = Field(min_length=10)
    missing: list[str] = []


class SynthesisFinding(BaseModel):
    text: str = Field(min_length=10)  # Bosnian
    confidence: float = Field(ge=0, le=1)


class SynthesisOutput(BaseModel):
    """The final report content (Bosnian). The number contract is enforced on ALL text."""

    narrative: str = Field(min_length=50)
    findings: list[SynthesisFinding] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    next_step: str = Field(min_length=10)


# ── API schemas ────────────────────────────────────────────────────────────────


class InvestigationCreate(BaseModel):
    question: str = Field(min_length=10, max_length=2000)
    signal_id: int | None = None


class InvestigationCreated(BaseModel):
    investigation_id: int
    status: str
    register: Literal["analiza"] = "analiza"


class InvestigationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    trigger: str
    question: str
    status: str
    model_tier: str | None
    started_at: datetime.datetime | None
    finished_at: datetime.datetime | None
    created_by: int | None
    signal_id: int | None
    created_at: datetime.datetime


class InvestigationStepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    step_no: int
    node: str | None
    tool: str | None
    input: dict[str, Any] | None
    output: dict[str, Any] | None
    at: datetime.datetime


class InvestigationDetail(BaseModel):
    investigation: InvestigationRead
    report: dict[str, Any] | None
    steps: list[InvestigationStepRead]
    # Pending proposed actions when status == needs_input (what the human approves).
    pending_actions: list[dict[str, Any]] = []


class InvestigationListResponse(BaseModel):
    items: list[InvestigationRead]


class ResumeRequest(BaseModel):
    decision: Literal["approve", "reject"]
    note: str | None = None


class ResumeResponse(BaseModel):
    investigation: InvestigationRead
    register: Literal["akcija"] = "akcija"
