"""Pydantic schemas for capability proposals (CSA Phase 3a)."""

import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from valeri_api.selfconfig.schemas import DecisionRead

ParamType = Literal["integer", "string", "date", "decimal"]
Entity = Literal["customer", "article", "segment", "company"]
Grain = Literal["scalar", "row", "series"]


class ProposalParam(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    type: ParamType
    required: bool = False


class ProposalCreate(BaseModel):
    """A drafted metric proposal (from a human or, in Phase 3b, the agent)."""

    name: str = Field(min_length=3, max_length=60, pattern=r"^[a-z][a-z0-9_]*$")
    description: str = Field(min_length=5)  # Bosnian
    entity: Entity
    grain: Grain
    params: list[ProposalParam] = []
    sql: str = Field(min_length=1)
    source_message_id: int | None = None


class ProposalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    entity: str
    grain: str
    params: list[dict] | list[ProposalParam]
    sql: str
    status: str
    created_by: int | None
    created_at: datetime.datetime
    activated_at: datetime.datetime | None


class ProposalListResponse(BaseModel):
    items: list[ProposalRead]


class ProposalDecisionResponse(BaseModel):
    proposal: ProposalRead
    decision: DecisionRead
