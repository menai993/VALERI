"""Signal → task pipeline: every confirmed signal becomes exactly one assigned task.

All derivations (assignee, owner_cc ranking, due dates) come from SQL.
The exactly-one invariant is enforced by flipping the signal to 'tasked' in the
same transaction as the task insert: a re-run finds no 'new' signals.
"""

import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.audit.task_log import log_task_event
from valeri_api.signals.models import Task
from valeri_api.signals.schemas import TaskCreationResult
from valeri_api.signals.templates import render_action, render_body, render_title

# New signals + everything needed to build their tasks, in one query:
# customer name (for templates), the due date (signal date + configured offset,
# computed in SQL), ordered deterministically.
_NEW_SIGNALS_SQL = """
SELECT s.id,
       s.rule,
       s.customer_id,
       s.article_id,
       s.evidence,
       s.created_at,
       c.name AS customer_name,
       s.created_at::date + (rc.value::text)::int AS due_date
FROM app.signal s
LEFT JOIN core.customer c ON c.id = s.customer_id
LEFT JOIN app.rule_config rc ON rc.rule = s.rule AND rc.param = 'task_due_days'
WHERE s.status = 'new'
ORDER BY s.id
"""

_CURRENT_REPS_SQL = """
SELECT DISTINCT ON (customer_id) customer_id, sales_rep_id
FROM core.customer_rep
ORDER BY customer_id, from_date DESC
"""

_TOP10_SQL = """
SELECT customer_id FROM core.customer_metrics
ORDER BY turnover_6m_avg_60d DESC NULLS LAST
LIMIT 10
"""


def create_tasks_from_signals(
    session: Session, as_of: datetime.date | None = None
) -> TaskCreationResult:
    """Turn every 'new' signal into exactly one open task (+ audit log entries)."""
    current_rep = {
        row.customer_id: row.sales_rep_id for row in session.execute(text(_CURRENT_REPS_SQL))
    }
    top10_customers = {row[0] for row in session.execute(text(_TOP10_SQL))}
    new_signals = session.execute(text(_NEW_SIGNALS_SQL)).all()

    result = TaskCreationResult()

    for signal in new_signals:
        if signal.due_date is None:
            # A rule without task_due_days config is a configuration bug — fail loudly,
            # never fall back to a hard-coded default (CLAUDE.md: thresholds in DB).
            raise LookupError(
                f"Rule {signal.rule!r} has no 'task_due_days' entry in app.rule_config"
            )

        context = {"customer_name": signal.customer_name or "nepoznat kupac"}
        task = Task(
            signal_id=signal.id,
            assignee_id=current_rep.get(signal.customer_id),
            owner_cc=signal.customer_id in top10_customers,
            title=render_title(signal.rule, context),
            body=render_body(signal.rule, signal.evidence, context),
            proposed_action=render_action(signal.rule),
            due_date=signal.due_date,
            status="open",
            register="preporuka",
        )
        session.add(task)
        session.flush()  # assign task.id

        # The same-transaction status flip enforces the exactly-one-task invariant.
        session.execute(
            text("UPDATE app.signal SET status = 'tasked' WHERE id = :id"), {"id": signal.id}
        )

        log_task_event(
            session,
            task.id,
            "created",
            {"signal_id": signal.id, "rule": signal.rule, "title": task.title},
        )
        log_task_event(
            session,
            task.id,
            "assigned",
            {"assignee_id": task.assignee_id, "owner_cc": task.owner_cc},
        )
        result.created += 1

    return result
