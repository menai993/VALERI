"""Pydantic schemas for the task pipeline and API (typed I/O per CLAUDE.md)."""

import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TaskRead(BaseModel):
    """A task with its AI-response envelope (register, confidence, evidence from the signal)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    signal_id: int | None
    assignee_id: int | None
    assignee_name: str | None = None
    owner_cc: bool
    title: str
    body: str | None
    proposed_action: str | None
    due_date: datetime.date | None
    status: str
    register: str
    created_at: datetime.datetime
    # Envelope fields joined from the source signal:
    rule: str | None = None
    confidence: Decimal | None = None
    conf_band: str | None = None
    evidence: dict[str, Any] | None = None
    # Customer context joined via the signal (NULL for manual tasks — P1):
    customer_id: int | None = None
    customer_name: str | None = None


class TaskCreate(BaseModel):
    """A manual, user-created task (P1): no signal, no AI envelope."""

    title: str = Field(min_length=2, max_length=300)
    body: str | None = None
    assignee_id: int
    due_date: datetime.date | None = None


class TaskListResponse(BaseModel):
    items: list[TaskRead]
    next_cursor: int | None = None


class TaskStatusUpdate(BaseModel):
    status: Literal["in_progress", "done", "dismissed"]


class FeedbackCreate(BaseModel):
    useful: bool
    reason: str | None = None


class FeedbackRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    useful: bool
    reason: str | None
    at: datetime.datetime


class TaskCreationResult(BaseModel):
    """What one pipeline run produced."""

    created: int = 0
    skipped_not_new: int = 0
