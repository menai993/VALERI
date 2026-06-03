"""M10 acceptance: the self-configuration loop (TDD — written before the implementation).

1. A dismissal creates EXACTLY ONE reversible decision + an active learned_rule.
2. The scanner suppresses the right FUTURE signal and logs suppression_hit.
3. A vague+broad request triggers confirm (nothing active until /rules/apply).
4. Undo restores (rule reverted + new decision + signals fire again).
Plus: autonomy boundary in rule_config, SQL effect estimates, PII masking,
threshold-kind reversibility, scope edits, and the API surface.

All LLM interaction uses fakes — no gateway needed.
"""

import datetime
import json
import re

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tests.conftest import login, make_client
from valeri_api.auth.models import AppUser
from valeri_api.llm.client import LLMResponse
from valeri_api.scanner.scan import run_scan
from valeri_api.seed.users import OWNER_EMAIL

# ── the fake Tier-1 proposer ──────────────────────────────────────────────────


class ProposerFakeLLMClient:
    """Returns a scripted RuleChangeProposal; {{KUPAC}} → the pseudonym in the prompt."""

    def __init__(self, proposal: dict) -> None:
        self.proposal_json = json.dumps(proposal, ensure_ascii=False)
        self.captured: list[dict[str, str]] = []
        self.model = "fake-tier1"

    def complete(self, system: str, user: str) -> LLMResponse:
        self.captured.append({"system": system, "user": user})
        text_out = self.proposal_json
        pseudonym = re.search(r"Kupac-[0-9a-f]{6}", user)
        if pseudonym:
            text_out = text_out.replace("{{KUPAC}}", pseudonym.group(0))
        return LLMResponse(text=text_out, model=self.model, tokens=100, latency_ms=50)


def entity_proposal(rule: str = "customer_decline") -> dict:
    """A narrow (auto-applicable) proposal: suppress this one customer for this rule."""
    return {
        "rule_type": "suppress",
        "scope": {
            "kind": "entity",
            "rule": rule,
            "entity_type": "customer",
            "entity_ref": "{{KUPAC}}",
        },
        "description": "Ne prijavljuj pad prometa za ovog kupca — sezonski obrazac kupovine.",
        "interpretation_confidence": 0.9,
    }


def category_proposal() -> dict:
    """A broad (confirm-required) proposal: suppress a whole segment."""
    return {
        "rule_type": "suppress",
        "scope": {"kind": "category", "rule": "customer_decline", "category": "kafić"},
        "description": "Ne prijavljuj pad prometa za sve kafiće — sezonska djelatnost.",
        "interpretation_confidence": 0.85,
    }


# ── fixtures ──────────────────────────────────────────────────────────────────


def _reset_app_tables(session: Session) -> None:
    session.execute(
        text(
            "TRUNCATE audit.ai_log, audit.task_log, app.task_feedback, app.approval, "
            "app.owner_report, app.tool_call_log, app.message, app.conversation, "
            "app.suppression_hit, app.decision, app.task, app.signal, app.learned_rule "
            "RESTART IDENTITY CASCADE"
        )
    )


@pytest.fixture(scope="module")
def selfconfig_db(db_engine: Engine, seed_data):
    """Seed + scan (signals + tasks) shared by the module; per-test work rolls back."""
    from valeri_api.seed.loader import load, reset

    as_of = datetime.date.fromisoformat(seed_data.manifest["as_of"])
    with Session(db_engine) as session:
        _reset_app_tables(session)
        reset(session)
        load(seed_data, session)
        run_scan(session, as_of=as_of, create_tasks=True)
        session.commit()

    yield db_engine, as_of

    with Session(db_engine) as session:
        _reset_app_tables(session)
        reset(session)
        load(seed_data, session)
        session.commit()


@pytest.fixture
def sc(selfconfig_db):
    """A rolled-back session + the owner user + a decline signal to dismiss."""
    engine, as_of = selfconfig_db
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)

    owner = session.query(AppUser).filter(AppUser.email == OWNER_EMAIL).one()
    signal = session.execute(
        text(
            "SELECT s.id, s.rule, s.customer_id, c.name AS customer_name "
            "FROM app.signal s JOIN core.customer c ON c.id = s.customer_id "
            "WHERE s.rule = 'customer_decline' AND s.status = 'tasked' "
            "ORDER BY s.id LIMIT 1"
        )
    ).one()

    try:
        yield session, owner, signal, as_of
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


def _decision_rows(session: Session) -> list:
    return session.execute(
        text("SELECT id, kind, actor, reversible, payload FROM app.decision ORDER BY id")
    ).all()


def _clear_scan_state(session: Session) -> None:
    """Remove prior scan output so a future scan starts fresh.

    Dismissed signals stay (they anchor learned rules via source_signal_id and,
    as in production, are never deleted).
    """
    session.execute(text("DELETE FROM app.suppression_hit"))
    session.execute(text("DELETE FROM audit.task_log"))
    session.execute(text("DELETE FROM app.task_feedback"))
    session.execute(text("DELETE FROM app.task"))
    session.execute(text("DELETE FROM app.signal WHERE status != 'dismissed'"))


def _active_rules(session: Session) -> list:
    return session.execute(
        text("SELECT id, rule_type, scope, status, autonomy FROM app.learned_rule ORDER BY id")
    ).all()


# ── 1. THE ACCEPTANCE: dismissal → exactly one reversible decision + active rule ──


def test_dismissal_creates_exactly_one_reversible_decision_and_active_rule(sc) -> None:
    from valeri_api.selfconfig.proposer import propose_from_dismissal

    session, owner, signal, _ = sc
    fake = ProposerFakeLLMClient(entity_proposal())

    draft_response = propose_from_dismissal(
        session, signal.id, "To je sezonski kupac, ne treba signal.", owner, client=fake
    )

    # Auto-applied (narrow entity scope, high confidence, small blast radius).
    assert draft_response.applied is True
    assert draft_response.requires_confirm is False
    assert draft_response.register == "akcija"

    # EXACTLY ONE decision: reversible, kind=suppression, actor=valeri (auto).
    decisions = _decision_rows(session)
    assert len(decisions) == 1
    assert decisions[0].kind == "suppression"
    assert decisions[0].actor == "valeri"
    assert decisions[0].reversible is True

    # EXACTLY ONE learned rule: active, auto_applied, scope carries the REAL customer id.
    rules = _active_rules(session)
    assert len(rules) == 1
    assert rules[0].status == "active"
    assert rules[0].autonomy == "auto_applied"
    assert rules[0].rule_type == "suppress"
    assert rules[0].scope["kind"] == "entity"
    assert rules[0].scope["entity_id"] == signal.customer_id  # resolved server-side
    assert "entity_ref" not in rules[0].scope  # no pseudonyms persisted

    # The signal is dismissed; its task is dismissed too (D6).
    signal_status = session.execute(
        text("SELECT status FROM app.signal WHERE id = :id"), {"id": signal.id}
    ).scalar()
    assert signal_status == "dismissed"
    task_status = session.execute(
        text("SELECT status FROM app.task WHERE signal_id = :id"), {"id": signal.id}
    ).scalar()
    assert task_status == "dismissed"

    # The Bosnian description is stored.
    description = session.execute(text("SELECT description FROM app.learned_rule")).scalar()
    assert "sezonski" in description.lower()


# ── 2. THE ACCEPTANCE: the scanner suppresses the future signal + logs the hit ──


def test_scanner_suppresses_future_signal_and_logs_hit(sc) -> None:
    from valeri_api.selfconfig.proposer import propose_from_dismissal

    session, owner, signal, as_of = sc
    customer_id = signal.customer_id
    fake = ProposerFakeLLMClient(entity_proposal())

    # Learn the rule (auto-applied).
    propose_from_dismissal(session, signal.id, "Sezonski kupac.", owner, client=fake)

    # Wipe prior scan output and re-scan: the suppression must hit the FUTURE detection.
    _clear_scan_state(session)
    result = run_scan(session, as_of=as_of, recompute=False, create_tasks=True)
    assert result.total_suppressed >= 1

    # The customer's decline signal is PERSISTED as suppressed (evidence kept), with no task.
    suppressed = session.execute(
        text(
            "SELECT id, evidence FROM app.signal "
            "WHERE rule = 'customer_decline' AND customer_id = :cid AND status = 'suppressed'"
        ),
        {"cid": customer_id},
    ).one()
    assert suppressed.evidence["value"] is not None  # evidence preserved
    task_count = session.execute(
        text("SELECT COUNT(*) FROM app.task WHERE signal_id = :sid"), {"sid": suppressed.id}
    ).scalar()
    assert task_count == 0

    # The suppression hit links the learned rule to that signal.
    hit = session.execute(
        text("SELECT learned_rule_id, signal_id FROM app.suppression_hit ORDER BY id DESC LIMIT 1")
    ).one()
    assert hit.signal_id == suppressed.id

    # Other customers' decline signals fired normally (new/tasked).
    others = session.execute(
        text(
            "SELECT COUNT(*) FROM app.signal "
            "WHERE rule = 'customer_decline' AND customer_id != :cid "
            "AND status IN ('new', 'tasked')"
        ),
        {"cid": customer_id},
    ).scalar()
    assert others >= 1

    # Re-running the scan again doesn't duplicate the suppressed signal — it adds a hit.
    hits_before = session.execute(text("SELECT COUNT(*) FROM app.suppression_hit")).scalar()
    suppressed_before = session.execute(
        text("SELECT COUNT(*) FROM app.signal WHERE status = 'suppressed'")
    ).scalar()
    run_scan(session, as_of=as_of, recompute=False, create_tasks=True)
    hits_after = session.execute(text("SELECT COUNT(*) FROM app.suppression_hit")).scalar()
    suppressed_after = session.execute(
        text("SELECT COUNT(*) FROM app.signal WHERE status = 'suppressed'")
    ).scalar()
    assert suppressed_after == suppressed_before  # no duplicates
    assert hits_after > hits_before  # but the recurrence is recorded


# ── 3. THE ACCEPTANCE: vague + broad → confirm ────────────────────────────────


def test_vague_broad_request_requires_confirm(sc) -> None:
    from valeri_api.selfconfig.applier import apply_rule
    from valeri_api.selfconfig.proposer import propose_from_dismissal

    session, owner, signal, _ = sc
    fake = ProposerFakeLLMClient(category_proposal())

    draft_response = propose_from_dismissal(
        session, signal.id, "Kafići su sezonski, nemoj ih prijavljivati.", owner, client=fake
    )

    # Requires confirm: NOTHING is active, NO decision exists yet.
    assert draft_response.applied is False
    assert draft_response.requires_confirm is True
    assert draft_response.register == "preporuka"
    assert _decision_rows(session) == []
    pending = session.execute(
        text("SELECT id, status, autonomy FROM app.learned_rule ORDER BY id")
    ).all()
    assert len(pending) == 1
    assert pending[0].status == "pending_confirm"

    # The blast radius is reported (SQL) for the one-tap confirm UI.
    assert draft_response.effect_estimate.total_signals >= 0

    # The scanner ignores pending rules: nothing gets suppressed by it.
    from valeri_api.rules.engine import load_active_suppressions

    assert load_active_suppressions(session) == []

    # One-tap confirm → active + exactly one decision (actor=user, confirmed).
    apply_response = apply_rule(session, pending[0].id, owner)
    assert apply_response.learned_rule.status == "active"
    assert apply_response.learned_rule.autonomy == "confirmed"

    decisions = _decision_rows(session)
    assert len(decisions) == 1
    assert decisions[0].kind == "suppression"
    assert decisions[0].actor == "user"
    assert decisions[0].reversible is True


# ── 4. THE ACCEPTANCE: Undo restores ──────────────────────────────────────────


def test_undo_restores(sc) -> None:
    from valeri_api.selfconfig.applier import undo_rule
    from valeri_api.selfconfig.proposer import propose_from_dismissal

    session, owner, signal, as_of = sc
    customer_id = signal.customer_id
    fake = ProposerFakeLLMClient(entity_proposal())

    # Learn + verify suppression works.
    response = propose_from_dismissal(session, signal.id, "Sezonski kupac.", owner, client=fake)
    rule_id = response.learned_rule.id
    original_decision_id = response.decision_id

    # Undo → reverted + a NEW undo decision referencing the original.
    undo_response = undo_rule(session, rule_id, owner)
    assert undo_response.learned_rule.status == "reverted"

    decisions = _decision_rows(session)
    assert len(decisions) == 2  # the original apply + the undo (append-only, never deleted)
    undo_decision = decisions[-1]
    assert undo_decision.kind == "undo"
    assert undo_decision.actor == "user"
    assert undo_decision.payload["reverted_decision_id"] == original_decision_id

    # Re-scan: the signal fires again (new), nothing suppressed, no new hits.
    _clear_scan_state(session)
    run_scan(session, as_of=as_of, recompute=False, create_tasks=True)

    revived = session.execute(
        text(
            "SELECT status FROM app.signal "
            "WHERE rule = 'customer_decline' AND customer_id = :cid AND status != 'dismissed'"
        ),
        {"cid": customer_id},
    ).scalar()
    assert revived == "tasked"  # detected + tasked again
    assert session.execute(text("SELECT COUNT(*) FROM app.suppression_hit")).scalar() == 0


# ── 5. the autonomy boundary lives in rule_config ─────────────────────────────


def test_autonomy_boundary_lives_in_rule_config(sc) -> None:
    from valeri_api.selfconfig.proposer import propose_from_dismissal

    session, owner, signal, _ = sc

    # Tighten the boundary: nothing may auto-apply (min confidence above the fake's 0.9).
    session.execute(
        text(
            "UPDATE app.rule_config SET value = CAST(:value AS jsonb) "
            "WHERE rule = 'selfconfig' AND param = 'auto_apply_min_confidence'"
        ),
        {"value": "0.99"},
    )

    fake = ProposerFakeLLMClient(entity_proposal())
    response = propose_from_dismissal(session, signal.id, "Sezonski kupac.", owner, client=fake)

    # The same narrow proposal now requires confirm — behaviour changed by config alone.
    assert response.applied is False
    assert response.requires_confirm is True
    assert _decision_rows(session) == []


# ── 6. effect estimate comes from SQL ─────────────────────────────────────────


def test_effect_estimate_matches_sql(sc) -> None:
    from valeri_api.selfconfig.effect import estimate_effect

    session, _, signal, _ = sc

    # Entity scope: signals of this customer in the window.
    scope = {"kind": "entity", "entity_type": "customer", "entity_id": signal.customer_id}
    estimate = estimate_effect(session, scope)

    sql_count = session.execute(
        text(
            "SELECT COUNT(*) FROM app.signal "
            "WHERE customer_id = :cid AND created_at > now() - make_interval(days => :window)"
        ),
        {"cid": signal.customer_id, "window": estimate.window_days},
    ).scalar()
    assert estimate.total_signals == sql_count

    # Category scope: signals of all customers in that segment.
    segment_scope = {"kind": "category", "category": "kafić", "rule": "customer_decline"}
    segment_estimate = estimate_effect(session, segment_scope)
    sql_segment = session.execute(
        text(
            "SELECT COUNT(*) FROM app.signal s JOIN core.customer c ON c.id = s.customer_id "
            "WHERE c.segment = 'kafić' AND s.rule = 'customer_decline' "
            "AND s.created_at > now() - make_interval(days => :window)"
        ),
        {"window": segment_estimate.window_days},
    ).scalar()
    assert segment_estimate.total_signals == sql_segment


# ── 7. the proposer masks PII ─────────────────────────────────────────────────


def test_proposer_masks_pii(sc, seed_data) -> None:
    from valeri_api.selfconfig.proposer import propose_from_dismissal

    session, owner, signal, _ = sc
    fake = ProposerFakeLLMClient(entity_proposal())

    propose_from_dismissal(
        session,
        signal.id,
        f"Kupac {signal.customer_name} je sezonski, ne treba signal.",
        owner,
        client=fake,
    )

    real_names = {customer["name"] for customer in seed_data.customers}

    # No prompt contains a real customer name; pseudonyms appear.
    all_prompts = "\n".join(item["system"] + "\n" + item["user"] for item in fake.captured)
    for name in real_names:
        assert name not in all_prompts, f"customer name {name!r} leaked into a proposer prompt"
    assert "Kupac-" in all_prompts

    # ai_log is equally clean.
    masked_inputs = [
        json.dumps(row[0], ensure_ascii=False)
        for row in session.execute(text("SELECT masked_input FROM audit.ai_log"))
    ]
    assert masked_inputs
    for masked in masked_inputs:
        for name in real_names:
            assert name not in masked

    # But the APPLIED rule's scope has the real id, and the description is rehydrated/human-facing.
    rule = session.execute(text("SELECT scope FROM app.learned_rule")).scalar()
    assert rule["entity_id"] == signal.customer_id


# ── 8. threshold-kind rules update rule_config reversibly ─────────────────────


def test_threshold_kind_updates_rule_config_reversibly(sc) -> None:
    from valeri_api.selfconfig.applier import apply_rule, undo_rule
    from valeri_api.selfconfig.proposer import propose_from_dismissal

    session, owner, signal, _ = sc

    original_value = session.execute(
        text(
            "SELECT value FROM app.rule_config "
            "WHERE rule = 'customer_decline' AND param = 'decline_ratio_threshold'"
        )
    ).scalar()

    threshold_proposal = {
        "rule_type": "threshold",
        "scope": {
            "kind": "threshold",
            "rule": "customer_decline",
            "metric": "decline_ratio_threshold",
            "op": "<",
            "value": 0.5,
        },
        "description": "Prijavljuj pad prometa tek ispod 50% uobičajenog nivoa.",
        "interpretation_confidence": 0.9,
    }
    fake = ProposerFakeLLMClient(threshold_proposal)

    # Threshold kinds ALWAYS require confirm (D4 confirm_kinds).
    response = propose_from_dismissal(
        session, signal.id, "Prag je preosjetljiv, smanji ga na 50%.", owner, client=fake
    )
    assert response.requires_confirm is True

    # Confirm → rule_config updated + decision carries the old value.
    apply_response = apply_rule(session, response.learned_rule.id, owner)
    new_value = session.execute(
        text(
            "SELECT value FROM app.rule_config "
            "WHERE rule = 'customer_decline' AND param = 'decline_ratio_threshold'"
        )
    ).scalar()
    assert float(new_value) == 0.5
    assert apply_response.decision.kind == "threshold_change"
    assert float(apply_response.decision.payload["old_value"]) == float(original_value)

    # Undo → the threshold is restored.
    undo_rule(session, response.learned_rule.id, owner)
    restored = session.execute(
        text(
            "SELECT value FROM app.rule_config "
            "WHERE rule = 'customer_decline' AND param = 'decline_ratio_threshold'"
        )
    ).scalar()
    assert float(restored) == float(original_value)


# ── 9. scope edits write decisions ────────────────────────────────────────────


def test_edit_scope_writes_decision(sc) -> None:
    from valeri_api.selfconfig.applier import edit_scope
    from valeri_api.selfconfig.proposer import propose_from_dismissal

    session, owner, signal, _ = sc
    fake = ProposerFakeLLMClient(entity_proposal())
    response = propose_from_dismissal(session, signal.id, "Sezonski kupac.", owner, client=fake)

    new_scope = {
        "kind": "entity",
        "rule": None,  # widen: all rules for this customer
        "entity_type": "customer",
        "entity_id": signal.customer_id,
    }
    edit_scope(session, response.learned_rule.id, new_scope, owner)

    stored_scope = session.execute(
        text("SELECT scope FROM app.learned_rule WHERE id = :id"),
        {"id": response.learned_rule.id},
    ).scalar()
    assert stored_scope["rule"] is None

    decisions = _decision_rows(session)
    # apply (1) + scope edit (1) = 2; the edit decision records old + new scope.
    assert len(decisions) == 2
    assert decisions[-1].payload["old_scope"]["rule"] == "customer_decline"


# ── 10. the API surface ───────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_api_dismiss_apply_learned_rules_decisions(selfconfig_db, monkeypatch) -> None:
    """End-to-end through HTTP: dismiss → confirm → learned-rules → undo → decisions feed."""
    engine, _ = selfconfig_db

    # The API path uses the production client factory → patch it with the category fake
    # (requires confirm, exercising both endpoints).
    fake = ProposerFakeLLMClient(category_proposal())
    monkeypatch.setattr("valeri_api.llm.structured.get_llm_client", lambda: fake)

    owner_client = make_client()
    try:
        await login(owner_client, OWNER_EMAIL)

        # Find a tasked decline signal to dismiss.
        with engine.connect() as conn:
            signal_id = conn.execute(
                text(
                    "SELECT id FROM app.signal "
                    "WHERE rule = 'customer_decline' AND status = 'tasked' ORDER BY id LIMIT 1"
                )
            ).scalar()

        # Dismiss → category proposal → requires confirm.
        dismissed = await owner_client.post(
            f"/api/signals/{signal_id}/dismiss",
            json={"reason_text": "Svi kafići su sezonski."},
        )
        assert dismissed.status_code == 200, dismissed.text
        body = dismissed.json()
        assert body["requires_confirm"] is True
        assert body["applied"] is False
        assert body["register"] == "preporuka"
        rule_id = body["learned_rule"]["id"]

        # Apply (the one-tap confirm).
        applied = await owner_client.post("/api/rules/apply", json={"learned_rule_id": rule_id})
        assert applied.status_code == 200
        assert applied.json()["learned_rule"]["status"] == "active"
        decision_id = applied.json()["decision"]["id"]

        # Applying again → 409.
        again = await owner_client.post("/api/rules/apply", json={"learned_rule_id": rule_id})
        assert again.status_code == 409

        # The learned-rules list shows it with its origin and effect.
        listing = await owner_client.get("/api/learned-rules")
        assert listing.status_code == 200
        items = listing.json()["items"]
        assert any(item["id"] == rule_id and item["status"] == "active" for item in items)

        # Detail shows hits (none yet) + its decisions.
        detail = await owner_client.get(f"/api/learned-rules/{rule_id}")
        assert detail.status_code == 200
        assert detail.json()["rule"]["id"] == rule_id

        # Undo through the API → reverted + new decision.
        undone = await owner_client.post(f"/api/learned-rules/{rule_id}/undo")
        assert undone.status_code == 200
        assert undone.json()["learned_rule"]["status"] == "reverted"

        # The decisions feed shows everything, filterable by kind.
        decisions = await owner_client.get("/api/audit/decisions")
        assert decisions.status_code == 200
        kinds = [item["kind"] for item in decisions.json()["items"]]
        assert "suppression" in kinds and "undo" in kinds
        only_undo = await owner_client.get("/api/audit/decisions", params={"kind": "undo"})
        assert all(item["kind"] == "undo" for item in only_undo.json()["items"])
        assert any(
            item["payload"]["reverted_decision_id"] == decision_id
            for item in only_undo.json()["items"]
        )

        # 404 envelopes.
        missing = await owner_client.post("/api/rules/apply", json={"learned_rule_id": 999999})
        assert missing.status_code == 404
    finally:
        await owner_client.aclose()


@pytest.mark.anyio
async def test_api_rbac(selfconfig_db, seed_data, monkeypatch) -> None:
    """Reps can dismiss their own signals only; apply/undo is owner/admin; finance read-only."""
    engine, _ = selfconfig_db
    fake = ProposerFakeLLMClient(entity_proposal())
    monkeypatch.setattr("valeri_api.llm.structured.get_llm_client", lambda: fake)

    rep_user = next(user for user in seed_data.app_users if user["role"] == "sales_rep")
    rep_client = make_client()
    finance_client = make_client()
    try:
        await login(rep_client, rep_user["email"])
        from valeri_api.seed.users import FINANCE_EMAIL

        await login(finance_client, FINANCE_EMAIL)

        # A signal belonging to ANOTHER rep's customer → the rep gets 403 on dismiss.
        with engine.connect() as conn:
            foreign_signal = conn.execute(
                text(
                    "SELECT s.id FROM app.signal s "
                    "JOIN ("
                    "  SELECT DISTINCT ON (customer_id) customer_id, sales_rep_id "
                    "  FROM core.customer_rep ORDER BY customer_id, from_date DESC"
                    ") cur ON cur.customer_id = s.customer_id "
                    "WHERE cur.sales_rep_id != :rep_id AND s.status = 'tasked' LIMIT 1"
                ),
                {"rep_id": rep_user["sales_rep_id"]},
            ).scalar()

        denied = await rep_client.post(
            f"/api/signals/{foreign_signal}/dismiss", json={"reason_text": "Tuđi kupac."}
        )
        assert denied.status_code == 403

        # Reps cannot apply/undo rules (owner/admin only).
        rep_apply = await rep_client.post("/api/rules/apply", json={"learned_rule_id": 1})
        assert rep_apply.status_code == 403

        # Finance can read learned-rules + decisions but not mutate.
        assert (await finance_client.get("/api/learned-rules")).status_code == 200
        assert (await finance_client.get("/api/audit/decisions")).status_code == 200
        finance_apply = await finance_client.post("/api/rules/apply", json={"learned_rule_id": 1})
        assert finance_apply.status_code == 403
    finally:
        await rep_client.aclose()
        await finance_client.aclose()
