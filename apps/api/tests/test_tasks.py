"""M5 acceptance: signal → task pipeline, feedback, and the append-only task log.

- exactly one task per confirmed signal, with the customer's rep as assignee;
- owner_cc for top-10 customers (by baseline);
- Bosnian title/body render evidence values verbatim (never recomputed);
- due dates come from app.rule_config;
- feedback persists; audit.task_log records the full lifecycle.
"""

import datetime

import httpx
import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from valeri_api.scanner.scan import run_scan
from valeri_api.signals.pipeline import create_tasks_from_signals


def _reset_app_tables(session: Session) -> None:
    session.execute(
        text(
            "TRUNCATE audit.task_log, app.task_feedback, app.task, app.signal, "
            "app.learned_rule RESTART IDENTITY CASCADE"
        )
    )


def _restore_seed(engine: Engine, seed_data) -> None:
    from valeri_api.seed.loader import load, reset

    with Session(engine) as session:
        _reset_app_tables(session)
        reset(session)
        load(seed_data, session)
        session.commit()


@pytest.fixture(scope="module")
def tasked_db(db_engine: Engine, seed_data):
    """Seed → scan (signals) → pipeline (tasks). Yields (engine, as_of, manifest)."""
    from valeri_api.seed.loader import load, reset

    as_of = datetime.date.fromisoformat(seed_data.manifest["as_of"])
    with Session(db_engine) as session:
        _reset_app_tables(session)
        reset(session)
        load(seed_data, session)
        run_scan(session, as_of=as_of, create_tasks=False)
        create_tasks_from_signals(session, as_of=as_of)
        session.commit()

    yield db_engine, as_of, seed_data.manifest

    _restore_seed(db_engine, seed_data)


# ── pipeline invariants ───────────────────────────────────────────────────────


def test_one_task_per_signal(tasked_db) -> None:
    """Every confirmed signal has exactly one task; re-running the pipeline creates none."""
    engine, as_of, _ = tasked_db
    with engine.connect() as conn:
        unmatched = conn.execute(
            text(
                "SELECT s.id, s.status, COUNT(t.id) AS n_tasks "
                "FROM app.signal s LEFT JOIN app.task t ON t.signal_id = s.id "
                "GROUP BY s.id, s.status "
                "HAVING (s.status = 'tasked' AND COUNT(t.id) <> 1) "
                "    OR (s.status = 'new')"
            )
        ).all()
        assert unmatched == [], f"signals without exactly one task: {unmatched}"

        n_signals = conn.execute(
            text("SELECT COUNT(*) FROM app.signal WHERE status = 'tasked'")
        ).scalar()
        n_tasks = conn.execute(text("SELECT COUNT(*) FROM app.task")).scalar()
        assert n_signals == n_tasks
        assert n_tasks > 0

    # Idempotency: a second pipeline run creates zero tasks.
    with Session(engine) as session:
        rerun = create_tasks_from_signals(session, as_of=as_of)
        session.commit()
    assert rerun.created == 0


def test_assignee_is_customers_rep(tasked_db) -> None:
    """Every task's assignee equals the customer's current rep (independent SQL check)."""
    engine, _, _ = tasked_db
    with engine.connect() as conn:
        mismatches = conn.execute(text("""
                WITH current_rep AS (
                  SELECT DISTINCT ON (customer_id) customer_id, sales_rep_id
                  FROM core.customer_rep
                  ORDER BY customer_id, from_date DESC
                )
                SELECT t.id
                FROM app.task t
                JOIN app.signal s ON s.id = t.signal_id
                JOIN current_rep cr ON cr.customer_id = s.customer_id
                WHERE t.assignee_id IS DISTINCT FROM cr.sales_rep_id
                """)).all()
        assert mismatches == [], f"tasks with wrong assignee: {[r[0] for r in mismatches]}"


def test_owner_cc_for_top10_customers(tasked_db) -> None:
    """owner_cc is true exactly for tasks of top-10-by-baseline customers."""
    engine, _, _ = tasked_db
    with engine.connect() as conn:
        top10 = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT customer_id FROM core.customer_metrics "
                    "ORDER BY turnover_6m_avg_60d DESC NULLS LAST LIMIT 10"
                )
            )
        }
        rows = conn.execute(
            text(
                "SELECT t.id, s.customer_id, t.owner_cc FROM app.task t "
                "JOIN app.signal s ON s.id = t.signal_id"
            )
        ).all()

    assert rows
    for task_id, customer_id, owner_cc in rows:
        expected = customer_id in top10
        assert (
            owner_cc == expected
        ), f"task {task_id}: owner_cc={owner_cc}, expected {expected} (customer {customer_id})"


def test_task_carries_evidence_and_register(tasked_db) -> None:
    """Every task: register preporuka, signal evidence reachable, Bosnian text present."""
    engine, _, _ = tasked_db
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT t.id, t.register, t.title, t.body, t.proposed_action, t.due_date, "
                "       s.evidence, s.confidence, s.conf_band "
                "FROM app.task t JOIN app.signal s ON s.id = t.signal_id"
            )
        ).all()

    assert rows
    for row in rows:
        assert row.register == "preporuka"
        assert row.title and len(row.title) > 5
        assert row.body and "Brojke iz baze · SQL" in row.body
        assert row.proposed_action
        assert row.due_date is not None
        assert row.evidence is not None
        assert row.confidence is not None and row.conf_band is not None


def test_body_numbers_equal_signal_evidence(tasked_db) -> None:
    """Contract (principle 1): numbers in a decline task body are evidence values verbatim."""
    engine, _, manifest = tasked_db
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT t.body, s.evidence FROM app.task t "
                "JOIN app.signal s ON s.id = t.signal_id "
                "WHERE s.rule = 'customer_decline'"
            )
        ).all()

    assert rows
    for body, evidence in rows:
        # The body must contain the evidence's value/baseline/delta_pct strings verbatim.
        assert str(evidence["value"]) in body
        assert str(evidence["baseline"]) in body
        assert str(evidence["delta_pct"]) in body


def test_due_dates_from_config(tasked_db) -> None:
    """due_date = signal date + task_due_days(rule), read from app.rule_config."""
    engine, _, _ = tasked_db
    with engine.connect() as conn:
        mismatches = conn.execute(text("""
                SELECT t.id
                FROM app.task t
                JOIN app.signal s ON s.id = t.signal_id
                JOIN app.rule_config rc
                  ON rc.rule = s.rule AND rc.param = 'task_due_days'
                WHERE t.due_date <> s.created_at::date + (rc.value::text)::int
                """)).all()
        assert mismatches == [], f"tasks with wrong due date: {[r[0] for r in mismatches]}"


# ── task log lifecycle + feedback ────────────────────────────────────────────


def test_task_log_lifecycle(tasked_db) -> None:
    """created + assigned at birth; actioned/outcome on status changes; feedback logged."""
    engine, _, _ = tasked_db
    with engine.connect() as conn:
        task_id = conn.execute(text("SELECT id FROM app.task ORDER BY id LIMIT 1")).scalar()

    from valeri_api.audit.task_log import log_task_event
    from valeri_api.signals.models import Task, TaskFeedback

    with Session(engine) as session:
        # Every task already has created + assigned events from the pipeline.
        events = [
            row[0]
            for row in session.execute(
                text("SELECT event FROM audit.task_log WHERE task_id = :id ORDER BY id"),
                {"id": task_id},
            )
        ]
        assert events[:2] == ["created", "assigned"]

        # Walk the rest of the lifecycle.
        task = session.get(Task, task_id)
        task.status = "in_progress"
        log_task_event(session, task_id, "actioned", {"status": "in_progress"})
        task.status = "done"
        log_task_event(session, task_id, "outcome", {"status": "done"})
        session.add(TaskFeedback(task_id=task_id, useful=True, reason="Korisno upozorenje"))
        log_task_event(session, task_id, "feedback", {"useful": True})
        session.commit()

    with engine.connect() as conn:
        events = [
            row[0]
            for row in conn.execute(
                text("SELECT event FROM audit.task_log WHERE task_id = :id ORDER BY id"),
                {"id": task_id},
            )
        ]
    assert events == ["created", "assigned", "actioned", "outcome", "feedback"]


def test_unknown_event_rejected(tasked_db) -> None:
    """The append-only writer only accepts the documented lifecycle events."""
    engine, _, _ = tasked_db
    from valeri_api.audit.task_log import log_task_event

    with Session(engine) as session:
        task_id = session.execute(text("SELECT id FROM app.task LIMIT 1")).scalar()
        with pytest.raises(ValueError):
            log_task_event(session, task_id, "deleted", {})


def test_feedback_persists(tasked_db) -> None:
    """Multiple feedback entries per task persist with reason and timestamp."""
    engine, _, _ = tasked_db
    from valeri_api.signals.models import TaskFeedback

    with Session(engine) as session:
        task_id = session.execute(text("SELECT id FROM app.task ORDER BY id DESC LIMIT 1")).scalar()
        session.add(TaskFeedback(task_id=task_id, useful=True, reason="Dobra preporuka"))
        session.add(TaskFeedback(task_id=task_id, useful=False, reason="Kupac je sezonski"))
        session.commit()

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT useful, reason, at FROM app.task_feedback WHERE task_id = :id ORDER BY id"
            ),
            {"id": task_id},
        ).all()
    assert len(rows) == 2
    assert rows[0].useful is True and rows[0].reason == "Dobra preporuka"
    assert rows[1].useful is False and rows[1].at is not None


# ── API ───────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_api_endpoints(tasked_db) -> None:
    """List/detail/status/feedback endpoints per api-spec, with the error envelope."""
    engine, _, _ = tasked_db
    from tests.conftest import login
    from valeri_api.main import app
    from valeri_api.seed.users import OWNER_EMAIL

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, OWNER_EMAIL)  # M8: tasks API requires authentication
        # List with pagination.
        listing = await client.get("/api/tasks", params={"limit": 5})
        assert listing.status_code == 200
        body = listing.json()
        assert len(body["items"]) == 5
        assert body["next_cursor"] is not None
        first_task = body["items"][0]
        assert first_task["register"] == "preporuka"
        assert first_task["evidence"] is not None
        assert first_task["confidence"] is not None

        # Filter by assignee.
        assignee = first_task["assignee_id"]
        filtered = await client.get("/api/tasks", params={"assignee": assignee})
        assert filtered.status_code == 200
        assert all(item["assignee_id"] == assignee for item in filtered.json()["items"])

        # Detail + viewed log.
        task_id = first_task["id"]
        detail = await client.get(f"/api/tasks/{task_id}")
        assert detail.status_code == 200
        with engine.connect() as conn:
            viewed = conn.execute(
                text(
                    "SELECT COUNT(*) FROM audit.task_log WHERE task_id = :id AND event = 'viewed'"
                ),
                {"id": task_id},
            ).scalar()
        assert viewed >= 1

        # 404 envelope.
        missing = await client.get("/api/tasks/9999999")
        assert missing.status_code == 404
        assert "error" in missing.json()

        # Status transition.
        moved = await client.post(f"/api/tasks/{task_id}/status", json={"status": "in_progress"})
        assert moved.status_code == 200
        assert moved.json()["status"] == "in_progress"
        invalid = await client.post(f"/api/tasks/{task_id}/status", json={"status": "nepostojeci"})
        assert invalid.status_code == 422

        # Feedback.
        feedback = await client.post(
            f"/api/tasks/{task_id}/feedback", json={"useful": False, "reason": "Nije relevantno"}
        )
        assert feedback.status_code == 201
        assert feedback.json()["useful"] is False

        with engine.connect() as conn:
            events = [
                row[0]
                for row in conn.execute(
                    text("SELECT event FROM audit.task_log WHERE task_id = :id ORDER BY id"),
                    {"id": task_id},
                )
            ]
        assert "actioned" in events and "feedback" in events


# ── standalone tests (rebuild the DB; must run AFTER all tasked_db tests) ──────


def test_no_task_for_non_new_signals(db_engine: Engine, seed_data) -> None:
    """Signals that are not status='new' (dismissed/suppressed) never get tasks."""
    from valeri_api.seed.loader import load, reset

    as_of = datetime.date.fromisoformat(seed_data.manifest["as_of"])
    with Session(db_engine) as session:
        _reset_app_tables(session)
        reset(session)
        load(seed_data, session)
        run_scan(session, as_of=as_of, create_tasks=False)
        # Dismiss every customer_decline signal before the pipeline runs.
        session.execute(
            text("UPDATE app.signal SET status = 'dismissed' WHERE rule = 'customer_decline'")
        )
        create_tasks_from_signals(session, as_of=as_of)
        session.commit()

    try:
        with db_engine.connect() as conn:
            decline_tasks = conn.execute(
                text(
                    "SELECT COUNT(*) FROM app.task t JOIN app.signal s ON s.id = t.signal_id "
                    "WHERE s.rule = 'customer_decline'"
                )
            ).scalar()
            other_tasks = conn.execute(text("SELECT COUNT(*) FROM app.task")).scalar()
        assert decline_tasks == 0, "dismissed signals received tasks"
        assert other_tasks > 0, "non-dismissed signals should still get tasks"
    finally:
        _restore_seed(db_engine, seed_data)


# ── scanner integration ───────────────────────────────────────────────────────


def test_scan_creates_tasks(db_engine: Engine, seed_data) -> None:
    """run_scan(create_tasks=True) produces signals AND their tasks in one go."""
    from valeri_api.seed.loader import load, reset

    as_of = datetime.date.fromisoformat(seed_data.manifest["as_of"])
    with Session(db_engine) as session:
        _reset_app_tables(session)
        reset(session)
        load(seed_data, session)
        result = run_scan(session, as_of=as_of, create_tasks=True)
        session.commit()

    try:
        assert result.tasks_created > 0
        with db_engine.connect() as conn:
            n_new = conn.execute(
                text("SELECT COUNT(*) FROM app.signal WHERE status = 'new'")
            ).scalar()
            n_tasks = conn.execute(text("SELECT COUNT(*) FROM app.task")).scalar()
        assert n_new == 0, "all signals should be tasked after a create_tasks scan"
        assert n_tasks == result.total_inserted
    finally:
        _restore_seed(db_engine, seed_data)
