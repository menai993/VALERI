"""Pydantic schemas for the conversation layer (typed I/O per CLAUDE.md).

IntentClassification and ChatAnswer are LLM output schemas — malformed output is
rejected and retried, never shown raw.
"""

import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Register = Literal["analiza", "preporuka", "akcija"]

INTENTS = ("question", "feedback_config", "investigation", "action", "help")

# The tools the intent router may pick from (must match tools/catalog.py).
ROUTABLE_TOOLS = (
    "query_metric",
    "compare_periods",
    "list_signals",
    "explain_signal",
    "get_customer_360",
    "get_client_knowledge",
    "create_task_draft",
    "propose_rule_change",
    "start_investigation",
)


class IntentClassification(BaseModel):
    """The Tier-1 router's output: what the user wants and which tool serves it."""

    intent: Literal["question", "feedback_config", "investigation", "action", "help"]
    tool: (
        Literal[
            "query_metric",
            "compare_periods",
            "list_signals",
            "explain_signal",
            "get_customer_360",
            "get_client_knowledge",
            "create_task_draft",
            "propose_rule_change",
            "start_investigation",
        ]
        | None
    ) = None
    # Tool parameters as the model extracted them (customer refs are pseudonyms;
    # the dispatcher maps them back to ids server-side).
    params: dict[str, Any] = {}
    confidence: float = Field(ge=0, le=1)


class ChatAnswer(BaseModel):
    """The narrated Bosnian reply (number-contract-checked against the tool output)."""

    text: str = Field(min_length=10)
    register: Register


# ── SSE events ────────────────────────────────────────────────────────────────


class SSEEvent(BaseModel):
    """One server-sent event of the chat stream."""

    type: Literal["tool_call", "register", "token", "card", "capture", "done", "error"]
    data: dict[str, Any] = {}


# ── API schemas ───────────────────────────────────────────────────────────────


class SessionCreateResponse(BaseModel):
    session_id: int


class SessionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str | None
    started_at: datetime.datetime


class SessionListResponse(BaseModel):
    items: list[SessionSummary]


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str | None
    register: Register | None
    tool_calls: list[dict[str, Any]] | None
    created_at: datetime.datetime


class SessionHistoryResponse(BaseModel):
    id: int
    title: str | None
    started_at: datetime.datetime
    messages: list[MessageRead]


class MessageCreate(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
