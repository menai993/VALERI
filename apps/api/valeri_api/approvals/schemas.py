"""Pydantic schemas for the approval workflow (typed I/O per CLAUDE.md)."""

import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class DraftMessage(BaseModel):
    """The LLM output schema for a customer-facing message draft.

    The draft is always an action awaiting approval (register 'akcija' is
    structural, not LLM-classified).
    """

    text: str = Field(min_length=20, description="Bosanski prijedlog poruke kupcu")


class ApprovalRead(BaseModel):
    """An approval row as served by the API (always register 'akcija' + status)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int | None
    kind: str
    status: str
    payload: dict[str, Any] | None
    decided_by: int | None
    decided_at: datetime.datetime | None
    register: Literal["akcija"] = "akcija"


class ApprovalListResponse(BaseModel):
    items: list[ApprovalRead]


class ApprovalDecision(BaseModel):
    """The owner's decision on a pending approval."""

    decision: Literal["approved", "rejected", "deferred"]
    note: str | None = None
