"""Inbox summary (P1): the one SQL aggregate behind the notifications bell.

Pure COUNTs (principle 1), RBAC-aware: pending approvals are an owner/admin
concern; a rep's due-task count covers only their own queue; finance has no
task queue. `alerts` is reserved for P2 job-failure alerting (always 0 here).
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.auth.deps import CurrentUser, visible_customer_ids
from valeri_api.db import get_session

router = APIRouter()


class InboxSummary(BaseModel):
    pending_approvals: int
    pending_clarifications: int
    proposed_kb_items: int
    tasks_due_today: int
    alerts: int = 0  # reserved: P2 job-failure alerting
    total: int


@router.get("/inbox/summary", response_model=InboxSummary)
def inbox_summary(
    session: Annotated[Session, Depends(get_session)],
    user: CurrentUser,
) -> InboxSummary:
    """What is waiting on a human right now — the bell badge and its breakdown."""
    approvals = 0
    if user.role in ("owner", "admin"):
        approvals = session.execute(
            text("SELECT count(*) FROM app.approval WHERE status = 'pending_approval'")
        ).scalar_one()

    clarifications = session.execute(
        text("SELECT count(*) FROM app.clarification WHERE status = 'pending'")
    ).scalar_one()

    # Proposed KB items are scoped exactly like /kb/pending (visible_customer_ids:
    # a rep sees their book + unresolved records) so the badge matches the queue.
    scope = visible_customer_ids(user, session)
    if scope is None:
        proposed = session.execute(
            text(
                "SELECT (SELECT count(*) FROM app.client_fact WHERE status = 'proposed')"
                " + (SELECT count(*) FROM app.commercial_event WHERE status = 'proposed')"
                " + (SELECT count(*) FROM app.client_relationship WHERE status = 'proposed')"
            )
        ).scalar_one()
    else:
        proposed = session.execute(
            text(
                "SELECT (SELECT count(*) FROM app.client_fact WHERE status = 'proposed'"
                "        AND (customer_id IS NULL OR customer_id = ANY(:scope)))"
                " + (SELECT count(*) FROM app.commercial_event WHERE status = 'proposed'"
                "        AND (customer_id IS NULL OR customer_id = ANY(:scope)))"
                " + (SELECT count(*) FROM app.client_relationship WHERE status = 'proposed'"
                "        AND (from_customer_id = ANY(:scope) OR to_customer_id = ANY(:scope)))"
            ),
            {"scope": sorted(scope)},
        ).scalar_one()

    # Tasks due (incl. overdue): reps see their own queue; finance has none.
    if user.role == "finance":
        due = 0
    else:
        rep_filter = " AND assignee_id = :rep" if user.role == "sales_rep" else ""
        due = session.execute(
            text(
                "SELECT count(*) FROM app.task "
                "WHERE status IN ('open', 'in_progress') AND due_date <= CURRENT_DATE" + rep_filter
            ),
            ({"rep": user.sales_rep_id} if user.role == "sales_rep" else {}),
        ).scalar_one()

    alerts = 0
    return InboxSummary(
        pending_approvals=approvals,
        pending_clarifications=clarifications,
        proposed_kb_items=proposed,
        tasks_due_today=due,
        alerts=alerts,
        total=approvals + clarifications + proposed + due + alerts,
    )
