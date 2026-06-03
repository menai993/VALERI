"""Rule application, undo and scope editing (M10).

Every state change here writes an append-only, reversible app.decision — the
"show the decision on the platform" guarantee. Threshold-kind rules additionally
update app.rule_config, with the old value preserved in the decision payload so
Undo can restore it exactly.
"""

import json
import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.audit.decision import log_decision
from valeri_api.audit.models import Decision
from valeri_api.auth.models import AppUser
from valeri_api.rules.models import LearnedRule
from valeri_api.selfconfig.schemas import ApplyResponse, DecisionRead, LearnedRuleRead

logger = logging.getLogger("valeri.selfconfig.applier")


class RuleNotFound(LookupError):
    """The referenced learned rule does not exist."""


class InvalidRuleState(Exception):
    """The rule is not in a state that allows this operation (e.g. already active)."""


# ── apply ─────────────────────────────────────────────────────────────────────


def auto_apply_rule(session: Session, rule: LearnedRule, user: AppUser) -> Decision:
    """Auto-apply a freshly proposed rule (low stakes). Actor = 'valeri' (the system decided)."""
    rule.status = "active"
    rule.autonomy = "auto_applied"
    decision = _write_apply_decision(session, rule, actor="valeri", user=user)
    session.flush()
    return decision


def apply_rule(session: Session, rule_id: int, user: AppUser) -> ApplyResponse:
    """The one-tap human confirm: pending_confirm → active. Actor = 'user'."""
    rule = _get_rule(session, rule_id)
    if rule.status != "pending_confirm":
        raise InvalidRuleState(
            f"Pravilo {rule_id} je u statusu {rule.status!r} — samo pravila koja čekaju "
            "potvrdu mogu biti primijenjena"
        )

    rule.status = "active"
    rule.autonomy = "confirmed"
    decision = _write_apply_decision(session, rule, actor="user", user=user)
    session.flush()
    return ApplyResponse(learned_rule=_rule_read(session, rule), decision=_decision_read(decision))


def _write_apply_decision(
    session: Session, rule: LearnedRule, actor: str, user: AppUser
) -> Decision:
    """The apply decision; threshold kinds also change rule_config (old value preserved)."""
    payload = {
        "learned_rule_id": rule.id,
        "scope": rule.scope,
        "effect_estimate": rule.effect_estimate,
        "initiated_by_user_id": user.id,
    }

    if rule.rule_type == "threshold":
        old_value = _apply_threshold_change(session, rule.scope)
        payload["old_value"] = old_value
        payload["new_value"] = rule.scope.get("value")
        kind = "threshold_change"
    else:
        kind = "suppression"

    return log_decision(
        session,
        kind=kind,
        actor=actor,
        summary=rule.description,
        payload=payload,
        reversible=True,
    )


def _apply_threshold_change(session: Session, scope: dict) -> object:
    """Update the target rule_config value; return the old value (for undo)."""
    target_rule = scope.get("rule")
    target_param = scope.get("metric")
    new_value = scope.get("value")
    if not target_rule or not target_param or new_value is None:
        raise InvalidRuleState("Threshold pravilo mora imati rule, metric i value u opsegu")

    old_value = session.execute(
        text("SELECT value FROM app.rule_config WHERE rule = :rule AND param = :param"),
        {"rule": target_rule, "param": target_param},
    ).scalar()
    if old_value is None:
        raise InvalidRuleState(f"Prag {target_rule}.{target_param} ne postoji u rule_config")

    session.execute(
        text(
            "UPDATE app.rule_config SET value = CAST(:value AS jsonb), updated_at = now() "
            "WHERE rule = :rule AND param = :param"
        ),
        {"value": json.dumps(new_value), "rule": target_rule, "param": target_param},
    )
    return old_value


# ── undo ──────────────────────────────────────────────────────────────────────


def undo_rule(session: Session, rule_id: int, user: AppUser) -> ApplyResponse:
    """Revert a rule: status='reverted' + a NEW undo decision (append-only, never deletes)."""
    rule = _get_rule(session, rule_id)
    if rule.status not in ("active", "pending_confirm"):
        raise InvalidRuleState(f"Pravilo {rule_id} je već u statusu {rule.status!r}")

    # Find the decision that applied this rule (None when it was never applied).
    original_decision_id = session.execute(
        text(
            "SELECT id FROM app.decision "
            "WHERE kind IN ('suppression', 'threshold_change') "
            "AND (payload->>'learned_rule_id')::bigint = :rule_id "
            "ORDER BY id DESC LIMIT 1"
        ),
        {"rule_id": rule_id},
    ).scalar()

    payload = {
        "learned_rule_id": rule.id,
        "reverted_decision_id": original_decision_id,
        "initiated_by_user_id": user.id,
    }

    # Threshold rules: restore the old value recorded in the apply decision.
    if rule.rule_type == "threshold" and original_decision_id is not None:
        old_value = session.execute(
            text("SELECT payload->'old_value' FROM app.decision WHERE id = :id"),
            {"id": original_decision_id},
        ).scalar()
        if old_value is not None:
            session.execute(
                text(
                    "UPDATE app.rule_config SET value = CAST(:value AS jsonb), updated_at = now() "
                    "WHERE rule = :rule AND param = :param"
                ),
                {
                    "value": json.dumps(old_value),
                    "rule": rule.scope.get("rule"),
                    "param": rule.scope.get("metric"),
                },
            )
            payload["restored_value"] = old_value

    rule.status = "reverted"
    decision = log_decision(
        session,
        kind="undo",
        actor="user",
        summary=f"Poništeno pravilo: {rule.description}",
        payload=payload,
        reversible=False,  # an undo is final; re-learning creates a new rule
        reverted_decision_id=original_decision_id,
    )
    session.flush()
    return ApplyResponse(learned_rule=_rule_read(session, rule), decision=_decision_read(decision))


# ── scope editing ─────────────────────────────────────────────────────────────


def edit_scope(session: Session, rule_id: int, new_scope: dict, user: AppUser) -> ApplyResponse:
    """Change a rule's scope; the decision records old + new (reversible)."""
    rule = _get_rule(session, rule_id)
    if rule.status not in ("active", "pending_confirm"):
        raise InvalidRuleState(f"Pravilo {rule_id} je u statusu {rule.status!r}")

    old_scope = dict(rule.scope)
    rule.scope = new_scope
    decision = log_decision(
        session,
        kind="threshold_change" if rule.rule_type == "threshold" else "suppression",
        actor="user",
        summary=f"Izmijenjen opseg pravila: {rule.description}",
        payload={
            "learned_rule_id": rule.id,
            "old_scope": old_scope,
            "new_scope": new_scope,
            "initiated_by_user_id": user.id,
        },
        reversible=True,
    )
    session.flush()
    return ApplyResponse(learned_rule=_rule_read(session, rule), decision=_decision_read(decision))


# ── shared ────────────────────────────────────────────────────────────────────


def _get_rule(session: Session, rule_id: int) -> LearnedRule:
    rule = session.get(LearnedRule, rule_id)
    if rule is None:
        raise RuleNotFound(f"Naučeno pravilo {rule_id} ne postoji")
    return rule


def _rule_read(session: Session, rule: LearnedRule) -> LearnedRuleRead:
    hit_count = session.execute(
        text("SELECT COUNT(*) FROM app.suppression_hit WHERE learned_rule_id = :id"),
        {"id": rule.id},
    ).scalar()
    return LearnedRuleRead(
        id=rule.id,
        source_signal_id=rule.source_signal_id,
        source_message_id=rule.source_message_id,
        domain=rule.domain,
        rule_type=rule.rule_type,
        scope=rule.scope,
        description=rule.description,
        effect_estimate=rule.effect_estimate,
        status=rule.status,
        autonomy=rule.autonomy,
        created_by=rule.created_by,
        created_at=rule.created_at,
        expires_at=rule.expires_at,
        suppression_count=hit_count or 0,
    )


def _decision_read(decision: Decision) -> DecisionRead:
    return DecisionRead(
        id=decision.id,
        kind=decision.kind,
        actor=decision.actor,
        summary=decision.summary,
        payload=decision.payload,
        reversible=decision.reversible,
        reverted_decision_id=decision.reverted_decision_id,
        created_at=decision.created_at,
    )
