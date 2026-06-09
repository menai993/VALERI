"""Tasks API (M5): list, detail, status transitions, feedback — per docs/api-spec.md.

Every response carries the AI-response envelope fields (register, confidence,
conf_band, evidence) joined from the task's source signal.

RBAC (M8): owner/admin see all tasks; a sales_rep sees only their own
(assignee = their rep row); finance has no task access.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.audit.task_log import log_task_event
from valeri_api.auth.deps import require_roles
from valeri_api.auth.models import AppUser
from valeri_api.db import get_session
from valeri_api.signals.models import Task, TaskFeedback
from valeri_api.signals.schemas import (
    FeedbackCreate,
    FeedbackRead,
    TaskCreate,
    TaskListResponse,
    TaskRead,
    TaskStatusUpdate,
)

router = APIRouter()

# Finance is deliberately absent: task queues are rep/owner work surfaces (D2).
TaskUser = Annotated[AppUser, Depends(require_roles("owner", "admin", "sales_rep"))]


def _assert_task_visible(user: AppUser, assignee_id: int | None, task_id: int) -> None:
    """Reps may only touch their own tasks (owner/admin see all)."""
    if user.role == "sales_rep" and assignee_id != user.sales_rep_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "forbidden", "message": f"Nemate pristup zadatku {task_id}"},
        )


_TASK_SELECT = """
SELECT t.id, t.signal_id, t.assignee_id, t.owner_cc, t.title, t.body, t.proposed_action,
       t.due_date, t.status, t.register, t.created_at,
       r.name AS assignee_name,
       s.rule, s.confidence, s.conf_band, s.evidence,
       s.customer_id, c.name AS customer_name
FROM app.task t
LEFT JOIN app.signal s ON s.id = t.signal_id
LEFT JOIN core.customer c ON c.id = s.customer_id
LEFT JOIN core.sales_rep r ON r.id = t.assignee_id
"""


def _row_to_task(row) -> TaskRead:
    return TaskRead(
        id=row.id,
        signal_id=row.signal_id,
        assignee_id=row.assignee_id,
        assignee_name=row.assignee_name,
        owner_cc=row.owner_cc,
        title=row.title,
        body=row.body,
        proposed_action=row.proposed_action,
        due_date=row.due_date,
        status=row.status,
        register=row.register,
        created_at=row.created_at,
        rule=row.rule,
        confidence=row.confidence,
        conf_band=row.conf_band,
        evidence=row.evidence,
        customer_id=row.customer_id,
        customer_name=row.customer_name,
    )


def _not_found(task_id: int) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"code": "not_found", "message": f"Task {task_id} not found"},
    )


@router.get("/tasks", response_model=TaskListResponse)
def list_tasks(
    session: Annotated[Session, Depends(get_session)],
    user: TaskUser,
    assignee: int | None = None,
    status: str | None = None,
    rule: str | None = None,
    due: str | None = None,
    limit: int = 50,
    cursor: int | None = None,
) -> TaskListResponse:
    """List tasks, filterable by assignee/status/rule/due, cursor-paginated by id.

    ?due=today → open/in-progress tasks due today or earlier (the Danas view);
    ?due=overdue → strictly past due. Due-filtered lists are due-date ordered.
    """
    limit = max(1, min(limit, 200))
    if due is not None and due not in ("today", "overdue"):
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_due", "message": f"Nepoznat due filter: {due}"},
        )
    # Reps are forced onto their own task queue regardless of the filter they pass.
    if user.role == "sales_rep":
        assignee = user.sales_rep_id

    due_clause = ""
    if due == "today":
        due_clause = " AND t.status IN ('open', 'in_progress') AND t.due_date <= CURRENT_DATE"
    elif due == "overdue":
        due_clause = " AND t.status IN ('open', 'in_progress') AND t.due_date < CURRENT_DATE"
    order_by = "ORDER BY t.due_date, t.id" if due is not None else "ORDER BY t.id"

    rows = session.execute(
        text(
            _TASK_SELECT
            + """
            WHERE (CAST(:assignee AS bigint) IS NULL OR t.assignee_id = :assignee)
              AND (CAST(:status AS text) IS NULL OR t.status::text = :status)
              AND (CAST(:rule AS text) IS NULL OR s.rule = :rule)
              AND (CAST(:cursor AS bigint) IS NULL OR t.id > :cursor)
            """
            + due_clause
            + f"""
            {order_by}
            LIMIT :limit_plus_one
            """
        ),
        {
            "assignee": assignee,
            "status": status,
            "rule": rule,
            "cursor": cursor,
            "limit_plus_one": limit + 1,
        },
    ).all()

    has_more = len(rows) > limit
    items = [_row_to_task(row) for row in rows[:limit]]
    return TaskListResponse(items=items, next_cursor=items[-1].id if has_more and items else None)


@router.post("/tasks", status_code=201, response_model=TaskRead)
def create_task(
    body: TaskCreate,
    session: Annotated[Session, Depends(get_session)],
    user: TaskUser,
) -> TaskRead:
    """Create a MANUAL task (P1): user data, no signal, no AI envelope.

    A sales_rep is always self-assigned (spoofed assignee ignored); owner/admin
    may assign anyone. The append-only task_log records 'created'.
    """
    assignee_id = body.assignee_id
    if user.role == "sales_rep":
        if user.sales_rep_id is None:
            raise HTTPException(
                status_code=403,
                detail={"code": "forbidden", "message": "Korisnik nije povezan s komercijalistom"},
            )
        assignee_id = user.sales_rep_id

    task = Task(
        signal_id=None,
        assignee_id=assignee_id,
        title=body.title,
        body=body.body,
        due_date=body.due_date,
        status="open",
    )
    session.add(task)
    session.flush()
    log_task_event(session, task.id, "created", {"manual": True, "by_user": user.id})
    session.commit()

    row = session.execute(text(_TASK_SELECT + " WHERE t.id = :id"), {"id": task.id}).one()
    return _row_to_task(row)


@router.get("/tasks/{task_id}", response_model=TaskRead)
def get_task(
    task_id: int,
    session: Annotated[Session, Depends(get_session)],
    user: TaskUser,
) -> TaskRead:
    """Task detail. Records a 'viewed' lifecycle event."""
    row = session.execute(text(_TASK_SELECT + " WHERE t.id = :id"), {"id": task_id}).first()
    if row is None:
        raise _not_found(task_id)
    _assert_task_visible(user, row.assignee_id, task_id)

    log_task_event(session, task_id, "viewed", None)
    session.commit()
    return _row_to_task(row)


@router.post("/tasks/{task_id}/status", response_model=TaskRead)
def update_status(
    task_id: int,
    body: TaskStatusUpdate,
    session: Annotated[Session, Depends(get_session)],
    user: TaskUser,
) -> TaskRead:
    """Transition a task's status; logs 'actioned' (in_progress) or 'outcome' (done/dismissed)."""
    task = session.get(Task, task_id)
    if task is None:
        raise _not_found(task_id)
    _assert_task_visible(user, task.assignee_id, task_id)

    task.status = body.status
    event = "actioned" if body.status == "in_progress" else "outcome"
    log_task_event(session, task_id, event, {"status": body.status})
    session.commit()

    row = session.execute(text(_TASK_SELECT + " WHERE t.id = :id"), {"id": task_id}).one()
    return _row_to_task(row)


@router.post("/tasks/{task_id}/feedback", status_code=201, response_model=FeedbackRead)
def add_feedback(
    task_id: int,
    body: FeedbackCreate,
    session: Annotated[Session, Depends(get_session)],
    user: TaskUser,
) -> FeedbackRead:
    """Record rep/owner feedback on a task (the M10 learning loop's raw material)."""
    task = session.get(Task, task_id)
    if task is None:
        raise _not_found(task_id)
    _assert_task_visible(user, task.assignee_id, task_id)

    feedback = TaskFeedback(
        task_id=task_id, useful=body.useful, reason=body.reason, by_user=user.id
    )
    session.add(feedback)
    session.flush()
    log_task_event(session, task_id, "feedback", {"useful": body.useful, "reason": body.reason})
    session.commit()
    session.refresh(feedback)
    return FeedbackRead.model_validate(feedback)
