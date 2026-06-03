"""M11 acceptance: the over-suppression auditor + expiry (TDD — written before the implementation).

- value/volume drift detection is pure SQL over stored evidence;
- a drifted suppressed stream raises exactly ONE "Na provjeri" reactivation decision;
- keep/undo resolve a flag and the auditor respects the resolution;
- expired rules stop suppressing, are visibly marked, and restore thresholds;
- thresholds live in app.rule_config; PII is masked; narration falls back to a template.

All LLM interaction uses fakes — no gateway needed.
"""

import datetime
import json

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tests.test_selfconfig import (
    ProposerFakeLLMClient,
    _clear_scan_state,
    _reset_app_tables,
    entity_proposal,
)
from valeri_api.auth.models import AppUser
from valeri_api.llm.client import LLMResponse, LLMUnavailable
from valeri_api.scanner.scan import run_scan
from valeri_api.seed.users import OWNER_EMAIL

# ── fakes ─────────────────────────────────────────────────────────────────────


class AuditorFakeLLMClient:
    """Scripted Bosnian audit summary; records prompts for PII assertions."""

    def __init__(self, fail: bool = False) -> None:
        self.captured: list[dict[str, str]] = []
        self.fail = fail
        self.model = "fake-tier1"

    def complete(self, system: str, user: str) -> LLMResponse:
        self.captured.append({"system": system, "user": user})
        if self.fail:
            raise LLMUnavailable("scripted gateway failure")
        # No numbers in the reply → the number contract always holds.
        body = {
            "text": "Potisnuti obrazac se značajno pogoršao — pravilo je na provjeri.",
            "register": "analiza",
        }
        return LLMResponse(
            text=json.dumps(body, ensure_ascii=False), model=self.model, tokens=80, latency_ms=40
        )


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def audit_db(db_engine: Engine, seed_data):
    """Seed + scan once for the module; per-test work rolls back."""
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
def au(audit_db):
    """A rolled-back session + the owner + a tasked decline signal."""
    engine, as_of = audit_db
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)

    owner = session.query(AppUser).filter(AppUser.email == OWNER_EMAIL).one()
    signal = session.execute(
        text(
            "SELECT s.id, s.rule, s.customer_id, c.name AS customer_name, "
            "       (s.evidence->>'ratio')::float AS ratio "
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


# ── helpers ───────────────────────────────────────────────────────────────────


def _learn_and_suppress(session, owner, signal, as_of, rescans: int = 2) -> tuple[int, int]:
    """Dismiss → auto-applied entity rule → N rescans → (rule_id, suppressed_signal_id).

    Each rescan re-detects the pattern and records one suppression_hit, so
    `rescans` controls the hit count (audit_min_hits default is 2).
    """
    from valeri_api.selfconfig.proposer import propose_from_dismissal

    fake = ProposerFakeLLMClient(entity_proposal())
    response = propose_from_dismissal(session, signal.id, "Sezonski kupac.", owner, client=fake)
    rule_id = response.learned_rule.id

    _clear_scan_state(session)
    for _ in range(rescans):
        run_scan(session, as_of=as_of, recompute=False, create_tasks=True)

    suppressed_id = session.execute(
        text(
            "SELECT id FROM app.signal WHERE rule = 'customer_decline' "
            "AND customer_id = :cid AND status = 'suppressed'"
        ),
        {"cid": signal.customer_id},
    ).scalar()
    assert suppressed_id is not None, "the rescans must persist a suppressed signal"
    return rule_id, suppressed_id


def _plant_value_drift(session, suppressed_signal_id: int, source_ratio: float, factor: float):
    """Worsen the suppressed signal's stored ratio (what the engine refresh would write)."""
    session.execute(
        text(
            "UPDATE app.signal "
            "SET evidence = jsonb_set(evidence, '{ratio}', to_jsonb(CAST(:ratio AS text))) "
            "WHERE id = :id"
        ),
        {"ratio": f"{source_ratio * factor:.4f}", "id": suppressed_signal_id},
    )


def _plant_extra_hits(session, rule_id: int, signal_id: int, count: int):
    """Hand-insert extra suppression hits (the volume-drift raw material)."""
    for _ in range(count):
        session.execute(
            text(
                "INSERT INTO app.suppression_hit (learned_rule_id, signal_id) "
                "VALUES (:rule_id, :signal_id)"
            ),
            {"rule_id": rule_id, "signal_id": signal_id},
        )


def _flag_decisions(session) -> list:
    """All Na provjeri (reactivation/review) decisions, oldest first."""
    return session.execute(
        text(
            "SELECT id, kind, actor, summary, payload, reversible FROM app.decision "
            "WHERE kind = 'reactivation' AND (payload->>'review')::boolean ORDER BY id"
        )
    ).all()


# ── 1/2/3. drift detection is SQL and only fires on real drift ────────────────


def test_value_drift_detection_matches_sql(au) -> None:
    """A suppressed stream whose ratio materially worsened is flagged with SQL numbers."""
    from valeri_api.selfconfig.auditor import audit_suppressions

    session, owner, signal, as_of = au
    rule_id, suppressed_id = _learn_and_suppress(session, owner, signal, as_of)
    _plant_value_drift(session, suppressed_id, signal.ratio, factor=0.5)  # 50% worse → drift

    result = audit_suppressions(session, client=AuditorFakeLLMClient())

    flagged_ids = [report.learned_rule_id for report in result.flagged]
    assert rule_id in flagged_ids

    report = next(r for r in result.flagged if r.learned_rule_id == rule_id)
    assert report.drift_kind == "value"

    # The drift numbers equal direct SQL (principle 1: no model-computed numbers).
    sql_baseline = session.execute(
        text("SELECT (evidence->>'ratio')::float FROM app.signal WHERE id = :id"),
        {"id": signal.id},
    ).scalar()
    sql_current = session.execute(
        text("SELECT (evidence->>'ratio')::float FROM app.signal WHERE id = :id"),
        {"id": suppressed_id},
    ).scalar()
    assert report.baseline_value == pytest.approx(sql_baseline)
    assert report.current_value == pytest.approx(sql_current)
    assert report.drift_factor == pytest.approx(sql_current / sql_baseline)


def test_volume_drift_detection(au) -> None:
    """A rule hiding far more than predicted is flagged even without value drift."""
    from valeri_api.selfconfig.auditor import audit_suppressions

    session, owner, signal, as_of = au
    rule_id, suppressed_id = _learn_and_suppress(session, owner, signal, as_of)

    predicted = session.execute(
        text(
            "SELECT (effect_estimate->>'total_signals')::int FROM app.learned_rule WHERE id = :id"
        ),
        {"id": rule_id},
    ).scalar()
    volume_factor = session.execute(
        text(
            "SELECT value FROM app.rule_config "
            "WHERE rule = 'selfconfig' AND param = 'audit_volume_factor'"
        )
    ).scalar()
    # Push actual hits to factor × predicted (the 2 rescan hits already exist).
    needed = int(volume_factor) * max(1, int(predicted))
    _plant_extra_hits(session, rule_id, suppressed_id, count=max(0, needed - 2))

    result = audit_suppressions(session, client=AuditorFakeLLMClient())

    report = next(r for r in result.flagged if r.learned_rule_id == rule_id)
    assert report.drift_kind == "volume"
    # Numbers from SQL.
    sql_hits = session.execute(
        text("SELECT COUNT(*) FROM app.suppression_hit WHERE learned_rule_id = :id"),
        {"id": rule_id},
    ).scalar()
    assert report.actual_hits == sql_hits
    assert report.predicted_signals == predicted


def test_stable_stream_not_flagged(au) -> None:
    """A suppressed stream that has not changed produces no flag and no decision."""
    from valeri_api.selfconfig.auditor import audit_suppressions

    session, owner, signal, as_of = au
    _learn_and_suppress(session, owner, signal, as_of)
    # No drift planted: the suppressed evidence still matches the source signal.

    result = audit_suppressions(session, client=AuditorFakeLLMClient())

    assert result.flagged == []
    assert _flag_decisions(session) == []
    assert result.rules_checked >= 1  # the rule WAS examined, just not flagged


# ── 4. the Na provjeri decision: shape + dedup ────────────────────────────────


def test_na_provjeri_decision_shape_and_dedup(au) -> None:
    """Exactly one reactivation decision per drifted rule; re-running does not duplicate."""
    from valeri_api.selfconfig.auditor import audit_suppressions

    session, owner, signal, as_of = au
    rule_id, suppressed_id = _learn_and_suppress(session, owner, signal, as_of)
    _plant_value_drift(session, suppressed_id, signal.ratio, factor=0.5)

    audit_suppressions(session, client=AuditorFakeLLMClient())

    decisions = _flag_decisions(session)
    assert len(decisions) == 1
    flag = decisions[0]
    assert flag.kind == "reactivation"
    assert flag.actor == "valeri"  # the system raised it
    assert flag.payload["learned_rule_id"] == rule_id
    assert flag.payload["review"] is True
    assert flag.payload["drift_kind"] == "value"
    assert flag.payload["suppressed_signal_id"] == suppressed_id
    # The Bosnian summary exists and is non-trivial.
    assert len(flag.summary) > 20

    # Re-running the auditor must NOT raise a second flag for the same drift.
    rerun = audit_suppressions(session, client=AuditorFakeLLMClient())
    assert rerun.flagged == []
    assert rerun.skipped_already_flagged >= 1
    assert len(_flag_decisions(session)) == 1


# ── 5/6. keep / undo resolve a flag ───────────────────────────────────────────


def test_keep_resolves_flag_and_auditor_respects_it(au) -> None:
    """Zadrži writes an approval decision; the auditor re-flags only if drift worsens further."""
    from valeri_api.selfconfig.applier import keep_rule
    from valeri_api.selfconfig.auditor import audit_suppressions

    session, owner, signal, as_of = au
    rule_id, suppressed_id = _learn_and_suppress(session, owner, signal, as_of)
    _plant_value_drift(session, suppressed_id, signal.ratio, factor=0.5)
    audit_suppressions(session, client=AuditorFakeLLMClient())
    flag_id = _flag_decisions(session)[0].id

    # Keep: the owner explicitly accepts the rule despite the drift.
    keep_response = keep_rule(session, rule_id, owner)
    assert keep_response.decision.kind == "approval"
    assert keep_response.decision.payload["resolves_decision_id"] == flag_id
    assert keep_response.learned_rule.status == "active"  # still suppressing

    # Same drift → no new flag (the owner already accepted this state).
    rerun = audit_suppressions(session, client=AuditorFakeLLMClient())
    assert rerun.flagged == []
    assert len(_flag_decisions(session)) == 1

    # Drift worsens further beyond the kept state → a NEW flag is raised.
    _plant_value_drift(session, suppressed_id, signal.ratio, factor=0.2)
    worse = audit_suppressions(session, client=AuditorFakeLLMClient())
    assert [r.learned_rule_id for r in worse.flagged] == [rule_id]
    assert len(_flag_decisions(session)) == 2


def test_undo_resolves_flag(au) -> None:
    """Undoing a flagged rule reverts it; the auditor no longer considers it."""
    from valeri_api.selfconfig.applier import undo_rule
    from valeri_api.selfconfig.auditor import audit_suppressions

    session, owner, signal, as_of = au
    rule_id, suppressed_id = _learn_and_suppress(session, owner, signal, as_of)
    _plant_value_drift(session, suppressed_id, signal.ratio, factor=0.5)
    audit_suppressions(session, client=AuditorFakeLLMClient())

    undo_rule(session, rule_id, owner)

    rerun = audit_suppressions(session, client=AuditorFakeLLMClient())
    assert rerun.flagged == []
    assert rerun.rules_checked == 0  # reverted rules are not audited
    assert len(_flag_decisions(session)) == 1  # only the original flag remains


def test_keep_requires_open_flag(au) -> None:
    """Zadrži on a rule without an open flag is an error (nothing to resolve)."""
    from valeri_api.selfconfig.applier import InvalidRuleState, keep_rule
    from valeri_api.selfconfig.proposer import propose_from_dismissal

    session, owner, signal, _ = au
    fake = ProposerFakeLLMClient(entity_proposal())
    response = propose_from_dismissal(session, signal.id, "Sezonski kupac.", owner, client=fake)

    with pytest.raises(InvalidRuleState):
        keep_rule(session, response.learned_rule.id, owner)


# ── 7. expiry ─────────────────────────────────────────────────────────────────


def test_expired_rules_transition_and_stop_suppressing(au) -> None:
    """Past expires_at: scan marks the rule expired + decision + the signal fires again."""
    from valeri_api.selfconfig.proposer import propose_from_dismissal

    session, owner, signal, as_of = au
    fake = ProposerFakeLLMClient(entity_proposal())
    response = propose_from_dismissal(session, signal.id, "Sezonski kupac.", owner, client=fake)
    rule_id = response.learned_rule.id

    # Expire the rule, then rescan.
    session.execute(
        text("UPDATE app.learned_rule SET expires_at = now() - interval '1 day' WHERE id = :id"),
        {"id": rule_id},
    )
    _clear_scan_state(session)
    result = run_scan(session, as_of=as_of, recompute=False, create_tasks=True)

    # The rule is visibly expired (not just silently ignored).
    status = session.execute(
        text("SELECT status FROM app.learned_rule WHERE id = :id"), {"id": rule_id}
    ).scalar()
    assert status == "expired"

    # An expiry decision was written (actor=valeri, payload.expired).
    expiry_decisions = session.execute(
        text(
            "SELECT actor, payload FROM app.decision "
            "WHERE kind = 'reactivation' AND (payload->>'expired')::boolean"
        )
    ).all()
    assert len(expiry_decisions) == 1
    assert expiry_decisions[0].actor == "valeri"
    assert expiry_decisions[0].payload["learned_rule_id"] == rule_id

    # The customer's decline signal fires again (open, tasked) — nothing suppressed.
    assert result.total_suppressed == 0
    revived = session.execute(
        text(
            "SELECT status FROM app.signal WHERE rule = 'customer_decline' "
            "AND customer_id = :cid AND status IN ('new', 'tasked')"
        ),
        {"cid": signal.customer_id},
    ).scalar()
    assert revived is not None


def test_expired_threshold_rule_restores_config_value(au) -> None:
    """An expired threshold rule restores the original rule_config value."""
    from valeri_api.selfconfig.applier import apply_rule
    from valeri_api.selfconfig.auditor import expire_rules
    from valeri_api.selfconfig.proposer import propose_from_dismissal

    session, owner, signal, _ = au
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
    response = propose_from_dismissal(session, signal.id, "Smanji prag na 50%.", owner, client=fake)
    apply_rule(session, response.learned_rule.id, owner)

    # Confirm the threshold changed, then expire the rule.
    changed = session.execute(
        text(
            "SELECT value FROM app.rule_config "
            "WHERE rule = 'customer_decline' AND param = 'decline_ratio_threshold'"
        )
    ).scalar()
    assert float(changed) == 0.5

    session.execute(
        text("UPDATE app.learned_rule SET expires_at = now() - interval '1 day' WHERE id = :id"),
        {"id": response.learned_rule.id},
    )
    expired_ids = expire_rules(session)
    assert response.learned_rule.id in expired_ids

    restored = session.execute(
        text(
            "SELECT value FROM app.rule_config "
            "WHERE rule = 'customer_decline' AND param = 'decline_ratio_threshold'"
        )
    ).scalar()
    assert float(restored) == float(original_value)


# ── 8. thresholds live in rule_config ─────────────────────────────────────────


def test_auditor_thresholds_live_in_rule_config(au) -> None:
    """A mild drift is flagged or not purely based on the DB threshold."""
    from valeri_api.selfconfig.auditor import audit_suppressions

    session, owner, signal, as_of = au
    rule_id, suppressed_id = _learn_and_suppress(session, owner, signal, as_of)
    # Mild drift: ratio worsened to 80% of baseline (above the default 0.7 factor).
    _plant_value_drift(session, suppressed_id, signal.ratio, factor=0.8)

    not_flagged = audit_suppressions(session, client=AuditorFakeLLMClient())
    assert not_flagged.flagged == []

    # Tighten the threshold in DB → the SAME data now counts as drift.
    session.execute(
        text(
            "UPDATE app.rule_config SET value = CAST('0.9' AS jsonb) "
            "WHERE rule = 'selfconfig' AND param = 'audit_drift_factor'"
        )
    )
    flagged = audit_suppressions(session, client=AuditorFakeLLMClient())
    assert [r.learned_rule_id for r in flagged.flagged] == [rule_id]


# ── 9/10. masking + template fallback ─────────────────────────────────────────


def test_auditor_masks_pii(au, seed_data) -> None:
    """Auditor prompts and ai_log carry pseudonyms only — never real customer names."""
    from valeri_api.selfconfig.auditor import audit_suppressions

    session, owner, signal, as_of = au
    rule_id, suppressed_id = _learn_and_suppress(session, owner, signal, as_of)
    _plant_value_drift(session, suppressed_id, signal.ratio, factor=0.5)

    fake = AuditorFakeLLMClient()
    audit_suppressions(session, client=fake)

    real_names = {customer["name"] for customer in seed_data.customers}
    all_prompts = "\n".join(item["system"] + "\n" + item["user"] for item in fake.captured)
    assert fake.captured, "the auditor must narrate the flag through the LLM"
    for name in real_names:
        assert name not in all_prompts, f"customer name {name!r} leaked into an auditor prompt"
    assert "Kupac-" in all_prompts

    # The stored decision summary is rehydrated/human-facing (real name allowed there).
    flag = _flag_decisions(session)[0]
    assert "Kupac-" not in flag.summary


def test_auditor_narration_falls_back_to_template(au) -> None:
    """LLM failure → the flag decision is still written with a Bosnian template summary."""
    from valeri_api.selfconfig.auditor import audit_suppressions

    session, owner, signal, as_of = au
    rule_id, suppressed_id = _learn_and_suppress(session, owner, signal, as_of)
    _plant_value_drift(session, suppressed_id, signal.ratio, factor=0.5)

    result = audit_suppressions(session, client=AuditorFakeLLMClient(fail=True))

    assert [r.learned_rule_id for r in result.flagged] == [rule_id]
    decisions = _flag_decisions(session)
    assert len(decisions) == 1
    assert "na provjeri" in decisions[0].summary.lower()


# ── 11. scheduling ────────────────────────────────────────────────────────────


def test_scheduler_has_audit_job() -> None:
    """The worker scheduler includes the over-suppression audit job."""
    from valeri_api.scanner.scheduler import create_scheduler

    scheduler = create_scheduler()
    job_ids = {job.id for job in scheduler.get_jobs()}
    assert "over_suppression_audit" in job_ids


def test_weekly_cycle_includes_audit(au) -> None:
    """run_weekly_cycle runs the audit step: a drifted stream gets flagged by the Sunday job."""
    from valeri_api.scanner.scheduler import run_weekly_cycle

    session, owner, signal, as_of = au
    rule_id, suppressed_id = _learn_and_suppress(session, owner, signal, as_of)
    _plant_value_drift(session, suppressed_id, signal.ratio, factor=0.5)

    run_weekly_cycle(session, as_of=as_of, client=AuditorFakeLLMClient())

    assert [d.payload["learned_rule_id"] for d in _flag_decisions(session)] == [rule_id]


# ── 12. the engine refresh (the auditor's data source) ───────────────────────


def test_resuppression_refreshes_suppressed_evidence(au) -> None:
    """A re-detected suppressed pattern updates the stored evidence to the latest state."""
    from valeri_api.rules.engine import SignalDraft, insert_signals

    session, owner, signal, as_of = au
    rule_id, suppressed_id = _learn_and_suppress(session, owner, signal, as_of)

    hits_before = session.execute(
        text("SELECT COUNT(*) FROM app.suppression_hit WHERE learned_rule_id = :id"),
        {"id": rule_id},
    ).scalar()

    # The next detection of the same pattern carries WORSE evidence.
    worse_draft = SignalDraft(
        rule="customer_decline",
        customer_id=signal.customer_id,
        evidence={
            "metric": "turnover_60d",
            "ratio": "0.10",
            "value": "100.00",
            "baseline": "1000.00",
        },
        confidence="0.95",
        register="analiza",
    )
    insert_signals(session, [worse_draft])

    # The suppressed signal's evidence now shows the current (worse) state…
    refreshed = session.execute(
        text("SELECT (evidence->>'ratio')::float FROM app.signal WHERE id = :id"),
        {"id": suppressed_id},
    ).scalar()
    assert refreshed == pytest.approx(0.10)
    # …and the recurrence was recorded as one more hit (append-only).
    hits_after = session.execute(
        text("SELECT COUNT(*) FROM app.suppression_hit WHERE learned_rule_id = :id"),
        {"id": rule_id},
    ).scalar()
    assert hits_after == hits_before + 1
