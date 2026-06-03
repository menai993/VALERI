"""Tool: create_task_draft — the catalog's only mutation in M9.

Creates an open app.task for a customer (an INTERNAL action — principle 10 allows
auto-apply), assigned to the customer's current rep (from SQL). Per the /tool
mutation contract it writes BOTH the append-only task_log lifecycle events AND a
reversible app.decision (D1/D6). Never touches any source/ERP system.
"""

import datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import text

from valeri_api.audit.decision import log_decision
from valeri_api.audit.task_log import log_task_event
from valeri_api.signals.models import Task
from valeri_api.tools.base import ToolContext, ToolDefinition, ToolError

# Finance is deliberately absent: task management is rep/owner work (M8 D2).
TASK_ROLES = ("owner", "admin", "sales_rep")

_CURRENT_REP_SQL = """
SELECT sales_rep_id FROM (
    SELECT DISTINCT ON (customer_id) customer_id, sales_rep_id
    FROM core.customer_rep
    ORDER BY customer_id, from_date DESC
) current_assignment
WHERE customer_id = :customer_id
"""


class CreateTaskDraftInput(BaseModel):
    customer_id: int
    title: str = Field(min_length=5, max_length=200)
    body: str | None = None
    due_date: datetime.date | None = None


class CreateTaskDraftOutput(BaseModel):
    """The created task — visible, assigned, reversible (it can be dismissed)."""

    task_id: int
    title: str
    customer_id: int
    assignee_id: int | None
    due_date: Any | None
    status: str
    register: str
    decision_id: int


def _run(tool_input: CreateTaskDraftInput, context: ToolContext) -> CreateTaskDraftOutput:
    session = context.session

    # Row-level RBAC: reps create tasks only for their own customers.
    context.assert_customer_visible(tool_input.customer_id)

    customer_name = session.execute(
        text("SELECT name FROM core.customer WHERE id = :id"), {"id": tool_input.customer_id}
    ).scalar()
    if customer_name is None:
        raise ToolError(f"Kupac {tool_input.customer_id} ne postoji")

    # Assignee = the customer's current rep, from SQL (never guessed).
    assignee_id = session.execute(
        text(_CURRENT_REP_SQL), {"customer_id": tool_input.customer_id}
    ).scalar()

    task = Task(
        signal_id=None,  # user-requested, not signal-derived
        assignee_id=assignee_id,
        owner_cc=False,
        title=tool_input.title,
        body=tool_input.body,
        proposed_action=None,
        due_date=tool_input.due_date,
        status="open",
        register="akcija",  # a user-initiated action, visible as such
    )
    session.add(task)
    session.flush()

    # Append-only lifecycle log (principle 7).
    log_task_event(
        session,
        task.id,
        "created",
        {"source": "chat", "customer_id": tool_input.customer_id, "title": tool_input.title},
    )
    log_task_event(session, task.id, "assigned", {"assignee_id": assignee_id, "owner_cc": False})

    # The reversible decision (the /tool mutation contract; D1/D6).
    # kind='approval': the user's chat request IS the approval to create this task.
    decision = log_decision(
        session,
        kind="approval",
        actor="user",
        summary=f"Zadatak '{tool_input.title}' kreiran kroz razgovor za kupca {customer_name}",
        payload={
            "task_id": task.id,
            "customer_id": tool_input.customer_id,
            "title": tool_input.title,
            "created_by_user_id": context.user.id,
            "revert_hint": "dismiss the task to revert",
        },
        reversible=True,
    )

    return CreateTaskDraftOutput(
        task_id=task.id,
        title=task.title,
        customer_id=tool_input.customer_id,
        assignee_id=assignee_id,
        due_date=task.due_date,
        status=task.status,
        register=task.register,
        decision_id=decision.id,
    )


CREATE_TASK_DRAFT = ToolDefinition(
    name="create_task_draft",
    description=(
        "Kreira novi zadatak za kupca (dodjeljuje se komercijalisti kupca). Parametri: "
        "customer_id, title, body?, due_date?"
    ),
    input_schema=CreateTaskDraftInput,
    output_schema=CreateTaskDraftOutput,
    allowed_roles=TASK_ROLES,
    run=_run,
    mutates=True,
)
