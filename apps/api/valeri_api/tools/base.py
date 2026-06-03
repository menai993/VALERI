"""Tool catalog foundations: context, errors, and the tool definition contract.

A tool is a typed, RBAC-checked, audited function over SQL / the semantic layer.
The model never calls a tool directly — the dispatcher (catalog.py) does, after
validation and permission checks, and logs every call.
"""

from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel
from sqlalchemy.orm import Session

from valeri_api.auth.deps import visible_customer_ids
from valeri_api.auth.models import AppUser
from valeri_api.llm.client import LLMClient


class ToolError(Exception):
    """A tool failed in an expected, reportable way (bad input, missing entity)."""

    code = "tool_error"


class ToolPermissionError(ToolError):
    """RBAC denied the call (wrong role or out-of-scope data)."""

    code = "forbidden"


@dataclass
class ToolContext:
    """Everything a tool may use: the DB session, the calling user, the chat message.

    `llm_client` is the caller's gateway client (the conversation layer passes its
    own); tools that make LLM calls use it so the whole request shares one client.
    None → the tool falls back to the production factory.
    """

    session: Session
    user: AppUser
    message_id: int | None = None
    llm_client: LLMClient | None = None

    def visible_customers(self) -> set[int] | None:
        """RBAC row scope: None = unrestricted; a set for sales reps (fail closed)."""
        return visible_customer_ids(self.user, self.session)

    def assert_customer_visible(self, customer_id: int) -> None:
        """Raise ToolPermissionError when a rep references a customer outside their scope."""
        scope = self.visible_customers()
        if scope is not None and customer_id not in scope:
            raise ToolPermissionError(
                f"Korisnik nema pristup kupcu {customer_id} (RBAC opseg komercijaliste)"
            )


@dataclass(frozen=True)
class ToolDefinition:
    """One catalog entry: schemas + allowed roles + the implementation."""

    name: str
    description: str  # what the intent router tells the model this tool does
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    allowed_roles: tuple[str, ...]
    run: Callable[[BaseModel, ToolContext], BaseModel]
    # Marks tools that mutate state — these must write a reversible app.decision.
    mutates: bool = False
