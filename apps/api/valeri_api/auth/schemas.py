"""Pydantic schemas for auth + user management (typed I/O per CLAUDE.md)."""

import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Role = Literal["owner", "sales_rep", "finance", "admin"]

# Simple e-mail shape check (full validation is not a security boundary here —
# login compares against stored users; user creation is admin-only).
_EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class LoginRequest(BaseModel):
    email: str = Field(pattern=_EMAIL_PATTERN)
    password: str = Field(min_length=1)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    role: Role
    sales_rep_id: int | None
    preferred_language: str
    created_at: datetime.datetime


class LoginResponse(BaseModel):
    user: UserRead


class UserCreate(BaseModel):
    name: str = Field(min_length=1)
    email: str = Field(pattern=_EMAIL_PATTERN)
    role: Role
    password: str = Field(min_length=8)
    sales_rep_id: int | None = None
    preferred_language: str = "bs"


class UserUpdate(BaseModel):
    name: str | None = None
    role: Role | None = None
    password: str | None = Field(default=None, min_length=8)
    sales_rep_id: int | None = None
    preferred_language: str | None = None


class UserListResponse(BaseModel):
    items: list[UserRead]
