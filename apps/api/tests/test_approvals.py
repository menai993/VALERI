"""M7 acceptance: the approval workflow — the structural gate (TDD, principle 10).

8.  Internal actions (scan → tasks → report) auto-run with zero approvals needed.
9.  No customer-facing message can be sent without an approved approval row.
10. The full lifecycle: draft → pending_approval → approved/rejected → sent.
11. Report generation drafts win-back messages for decline/sleeping tasks.
12. Draft-message prompts are masked; stored drafts are rehydrated for humans.
13. The approvals API: list, filter, decide, 404/409 envelopes.

All LLM interaction uses fakes — no gateway needed.
"""

import datetime
import json

import httpx
import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tests.fakes import AutoFakeLLMClient


def _reset_app_tables(session: Session) -> None:
    session.execute(
        text(
            "TRUNCATE audit.ai_log, audit.task_log, app.task_feedback, app.approval, "
            "app.owner_report, app.task, app.signal, app.learned_rule RESTART IDENTITY CASCADE"
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
def approval_db(db_engine: Engine, seed_data):
    """The full weekly cycle (scan → tasks → report + drafts) with a fake LLM."""
    from valeri_api.scanner.scheduler import run_weekly_cycle
    from valeri_api.seed.loader import load, reset

    as_of = datetime.date.fromisoformat(seed_data.manifest["as_of"])
    fake = AutoFakeLLMClient()
    with Session(db_engine) as session:
        _reset_app_tables(session)
        reset(session)
        load(seed_data, session)
        scan_result, report = run_weekly_cycle(session, as_of=as_of, client=fake)
        session.commit()
        report_id = report.id
        n_signals = scan_result.total_inserted
        n_tasks = scan_result.tasks_created

    yield db_engine, report_id, n_signals, n_tasks, fake, as_of

    _restore_seed(db_engine, seed_data)


# ── 8. internal actions auto-run ──────────────────────────────────────────────


def test_internal_actions_auto_run(approval_db) -> None:
    """The whole scheduled cycle completed with zero approvals required."""
    engine, report_id, n_signals, n_tasks, _, _ = approval_db

    assert n_signals > 0, "the seed's planted cases must produce signals"
    assert n_tasks > 0, "every signal must have produced a task without approval"

    with engine.connect() as conn:
        # Tasks and the report exist — no internal action was blocked on approval.
        assert conn.execute(text("SELECT COUNT(*) FROM app.task")).scalar() == n_tasks
        report_count = conn.execute(
            text("SELECT COUNT(*) FROM app.owner_report WHERE id = :id"), {"id": report_id}
        ).scalar()
        assert report_count == 1

        # The only approval rows are customer-facing drafts; none is approved/sent —
        # i.e. nothing internal consumed an approval, and nothing external happened.
        statuses = {
            row[0] for row in conn.execute(text("SELECT DISTINCT status FROM app.approval"))
        }
        assert "approved" not in statuses
        assert "sent" not in statuses
        kinds = {row[0] for row in conn.execute(text("SELECT DISTINCT kind FROM app.approval"))}
        assert kinds <= {"message"}


# ── 9. the gate ───────────────────────────────────────────────────────────────


def test_customer_facing_cannot_send_without_approval(approval_db) -> None:
    """send_customer_message() raises unless the approval row is 'approved'."""
    from valeri_api.approvals.workflow import (
        ApprovalRequired,
        create_draft,
        decide,
        send_customer_message,
        submit_for_approval,
    )

    engine, *_ = approval_db

    # Everything in this test stays uncommitted (discarded when the session closes).
    with Session(engine) as session:
        task_id = session.execute(text("SELECT id FROM app.task ORDER BY id LIMIT 1")).scalar()

        # A draft cannot send.
        draft = create_draft(
            session, task_id=task_id, kind="message", payload={"message": "Testna poruka kupcu."}
        )
        with pytest.raises(ApprovalRequired):
            send_customer_message(session, draft.id)
        assert draft.status == "draft"

        # Pending approval cannot send.
        submit_for_approval(session, draft.id)
        with pytest.raises(ApprovalRequired):
            send_customer_message(session, draft.id)
        assert draft.status == "pending_approval"

        # Rejected cannot send.
        decide(session, draft.id, "rejected")
        with pytest.raises(ApprovalRequired):
            send_customer_message(session, draft.id)
        assert draft.status == "rejected"

        # Nothing was ever marked sent.
        n_sent = session.execute(
            text("SELECT COUNT(*) FROM app.approval WHERE status = 'sent'")
        ).scalar()
        assert n_sent == 0

        # Only an explicitly approved draft can send.
        approved = create_draft(
            session, task_id=task_id, kind="message", payload={"message": "Druga testna poruka."}
        )
        submit_for_approval(session, approved.id)
        decide(session, approved.id, "approved")
        sent = send_customer_message(session, approved.id)
        assert sent.status == "sent"


# ── 10. the lifecycle ─────────────────────────────────────────────────────────


def test_approval_lifecycle(approval_db) -> None:
    """draft → pending → approved (+decided_by/decided_at) → sent; invalid moves raise."""
    from valeri_api.approvals.workflow import (
        InvalidTransition,
        create_draft,
        decide,
        send_customer_message,
        submit_for_approval,
    )

    engine, *_ = approval_db
    with Session(engine) as session:
        task_id = session.execute(text("SELECT id FROM app.task ORDER BY id LIMIT 1")).scalar()

        # Happy path: draft → pending_approval → approved → sent.
        approval = create_draft(
            session,
            task_id=task_id,
            kind="message",
            payload={"message": "Poruka u testu lifecycle-a."},
        )
        assert approval.status == "draft"
        assert approval.payload["message"] == "Poruka u testu lifecycle-a."

        submit_for_approval(session, approval.id)
        assert approval.status == "pending_approval"

        decided = decide(session, approval.id, "approved", decided_by=42, note="Može.")
        assert decided.status == "approved"
        assert decided.decided_by == 42
        assert decided.decided_at is not None

        # M10: the human gate writes an append-only 'approval' decision.
        approval_decision = session.execute(
            text(
                "SELECT actor, payload FROM app.decision "
                "WHERE kind = 'approval' ORDER BY id DESC LIMIT 1"
            )
        ).one()
        assert approval_decision.actor == "user"
        assert approval_decision.payload["approval_id"] == approval.id
        assert approval_decision.payload["decided_by"] == 42

        sent = send_customer_message(session, approval.id)
        assert sent.status == "sent"

        # The rejected path terminates: no re-decision, no send.
        rejected = create_draft(
            session, task_id=task_id, kind="message", payload={"message": "Odbijena testna poruka."}
        )
        submit_for_approval(session, rejected.id)
        decide(session, rejected.id, "rejected", decided_by=42)
        assert rejected.status == "rejected"
        assert rejected.decided_at is not None
        with pytest.raises(InvalidTransition):
            decide(session, rejected.id, "approved", decided_by=42)

        # M10: rejection also lands in the decision log.
        rejection_decision = session.execute(
            text(
                "SELECT payload FROM app.decision "
                "WHERE kind = 'rejection' ORDER BY id DESC LIMIT 1"
            )
        ).one()
        assert rejection_decision.payload["approval_id"] == rejected.id

        # Invalid transitions raise.
        fresh = create_draft(
            session,
            task_id=task_id,
            kind="message",
            payload={"message": "Još jedna testna poruka."},
        )
        with pytest.raises(InvalidTransition):
            decide(session, fresh.id, "approved")  # cannot decide an unsubmitted draft
        submit_for_approval(session, fresh.id)
        with pytest.raises(InvalidTransition):
            submit_for_approval(session, fresh.id)  # cannot re-submit

        # 'deferred' keeps it pending and records no decision.
        deferred = decide(session, fresh.id, "deferred")
        assert deferred.status == "pending_approval"
        assert deferred.decided_at is None
        assert deferred.decided_by is None


# ── 11. drafts generated during report generation ────────────────────────────


def test_drafts_generated_for_decline_and_sleeping_tasks(approval_db) -> None:
    """One LLM-written message draft per decline/sleeping task; nothing else gets drafts."""
    engine, *_ = approval_db

    with engine.connect() as conn:
        # Every open decline/sleeping task has exactly one message draft.
        missing = conn.execute(
            text(
                "SELECT t.id FROM app.task t "
                "JOIN app.signal s ON s.id = t.signal_id "
                "WHERE s.rule IN ('customer_decline', 'sleeping_customer') "
                "  AND t.status = 'open' "
                "  AND NOT EXISTS (SELECT 1 FROM app.approval a "
                "                  WHERE a.task_id = t.id AND a.kind = 'message')"
            )
        ).all()
        assert missing == [], f"decline/sleeping tasks without a draft: {[r[0] for r in missing]}"

        dupes = conn.execute(
            text(
                "SELECT task_id FROM app.approval WHERE kind = 'message' "
                "GROUP BY task_id HAVING COUNT(*) > 1"
            )
        ).all()
        assert dupes == [], "a task must never get more than one message draft"

        # No drafts attached to tasks of other rules.
        wrong_rule = conn.execute(
            text(
                "SELECT a.id FROM app.approval a "
                "JOIN app.task t ON t.id = a.task_id "
                "JOIN app.signal s ON s.id = t.signal_id "
                "WHERE a.kind = 'message' "
                "  AND s.rule NOT IN ('customer_decline', 'sleeping_customer')"
            )
        ).all()
        assert wrong_rule == []

        # Drafts exist, are awaiting approval, and carry the full payload.
        rows = conn.execute(
            text("SELECT status, payload FROM app.approval WHERE kind = 'message'")
        ).all()

    assert rows, "the planted declines/sleeping customers must produce drafts"
    for status, payload in rows:
        assert status == "pending_approval", "generated drafts must await approval"
        assert payload["message"] and len(payload["message"]) >= 20
        assert payload["customer_name"]
        assert payload["rule"] in ("customer_decline", "sleeping_customer")
        assert payload["source"] in ("llm", "template")
        assert payload["register"] == "akcija"

    # With a working (fake) LLM client, drafts are LLM-written, not templates.
    assert any(payload["source"] == "llm" for _, payload in rows)


# ── 12. draft prompts are masked ──────────────────────────────────────────────


def test_draft_message_no_pii_in_prompt(approval_db, seed_data) -> None:
    """Draft prompts carry pseudonyms only; stored drafts get real names back."""
    from valeri_api.llm.prompts import MESSAGE_SYSTEM_PROMPT

    engine, _, _, _, fake, _ = approval_db

    real_customer_names = {customer["name"] for customer in seed_data.customers}
    contact_pii = set()
    for contact in seed_data.contacts:
        contact_pii.add(contact["name"])
        contact_pii.add(contact["email"])
        contact_pii.add(contact["phone"])

    # a) The draft-message prompts (identified by their system prompt) are masked.
    draft_prompts = [item for item in fake.captured if item["system"] == MESSAGE_SYSTEM_PROMPT]
    assert draft_prompts, "report generation should have prompted for message drafts"
    for item in draft_prompts:
        combined = item["system"] + "\n" + item["user"]
        for name in real_customer_names:
            assert name not in combined, f"customer name {name!r} leaked into a draft prompt"
        for pii in contact_pii:
            assert pii not in combined, f"contact PII {pii!r} leaked into a draft prompt"
        assert "Kupac-" in item["user"], "draft prompts must use pseudonyms"

    # b) Stored draft payloads (human-facing, post-rehydration): real names, no pseudonyms.
    with engine.connect() as conn:
        payloads = [
            row[0]
            for row in conn.execute(text("SELECT payload FROM app.approval WHERE kind = 'message'"))
        ]
    llm_payloads = [payload for payload in payloads if payload["source"] == "llm"]
    assert llm_payloads
    for payload in llm_payloads:
        assert "Kupac-" not in payload["message"], "stored drafts must be rehydrated"
    assert any(
        payload["customer_name"] in payload["message"] for payload in llm_payloads
    ), "LLM-drafted messages should address the customer by real (rehydrated) name"

    # c) ai_log.masked_input for draft calls is clean.
    with engine.connect() as conn:
        masked_inputs = [
            json.dumps(row[0], ensure_ascii=False)
            for row in conn.execute(text("SELECT masked_input FROM audit.ai_log"))
        ]
    assert masked_inputs
    for masked in masked_inputs:
        for name in real_customer_names:
            assert name not in masked
        for pii in contact_pii:
            assert pii not in masked


# ── 13. the API ───────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_api_approvals_list_and_decide(approval_db) -> None:
    """GET list/filter + POST decide with 404/409 error envelopes."""
    from tests.conftest import login
    from valeri_api.main import app
    from valeri_api.seed.users import OWNER_EMAIL

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, OWNER_EMAIL)  # M8: approvals are owner/admin only
        # List pending approvals.
        listing = await client.get("/api/approvals", params={"status": "pending_approval"})
        assert listing.status_code == 200
        items = listing.json()["items"]
        assert items, "the generated drafts must be listed"
        for item in items:
            assert item["status"] == "pending_approval"
            assert item["register"] == "akcija"
            assert item["payload"]["message"]
            assert item["task_id"] is not None

        # Decide: approve the first one.
        target = items[0]["id"]
        decided = await client.post(
            f"/api/approvals/{target}/decide", json={"decision": "approved", "note": "Odobravam."}
        )
        assert decided.status_code == 200
        assert decided.json()["status"] == "approved"
        assert decided.json()["decided_at"] is not None

        # Deciding an already-decided approval → 409 envelope.
        again = await client.post(f"/api/approvals/{target}/decide", json={"decision": "rejected"})
        assert again.status_code == 409
        assert "error" in again.json()

        # Unknown id → 404 envelope.
        missing = await client.post("/api/approvals/999999/decide", json={"decision": "approved"})
        assert missing.status_code == 404
        assert "error" in missing.json()

        # Reject another one.
        if len(items) > 1:
            second = items[1]["id"]
            rejected = await client.post(
                f"/api/approvals/{second}/decide", json={"decision": "rejected"}
            )
            assert rejected.status_code == 200
            assert rejected.json()["status"] == "rejected"

        # An invalid decision value → 422 (Pydantic validation).
        invalid = await client.post(f"/api/approvals/{target}/decide", json={"decision": "možda"})
        assert invalid.status_code == 422

        # Unfiltered list returns everything; the approved one is filterable.
        everything = await client.get("/api/approvals")
        assert everything.status_code == 200
        assert len(everything.json()["items"]) >= len(items)
        approved_only = await client.get("/api/approvals", params={"status": "approved"})
        assert any(item["id"] == target for item in approved_only.json()["items"])
