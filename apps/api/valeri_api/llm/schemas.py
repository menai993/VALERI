"""Pydantic output schemas — the only shapes an LLM response may take (CLAUDE.md).

Malformed output is rejected and retried, never shown raw.
"""

from typing import Literal

from pydantic import BaseModel, Field

from valeri_api.llm.masking import MaskingContext


class TaskNarration(BaseModel):
    """The narration the LLM must produce for one signal."""

    body: str = Field(min_length=20, description="Bosanski radni nalog za komercijalistu")
    register: Literal["analiza", "preporuka", "akcija"]
    confidence: float = Field(ge=0, le=1)


class NarrationResult(BaseModel):
    """A successful, validated narration plus what's needed to use it."""

    narration: TaskNarration
    model: str
    attempts: int
    # The pseudonym↔name mapping, needed by the caller to rehydrate the body
    # for human-facing output. Imported lazily to avoid a circular import.
    context: "MaskingContext"


class NarrationFailed(Exception):
    """Narration could not be produced/validated; the caller should fall back."""

    def __init__(self, reason: str, attempts: int = 0) -> None:
        super().__init__(reason)
        self.reason = reason
        self.attempts = attempts
