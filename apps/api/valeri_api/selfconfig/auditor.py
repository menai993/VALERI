"""The over-suppression auditor (M11): suppressed streams are re-examined, not forgotten.

Drift detection is pure SQL/Python over stored evidence (principle 1); the LLM only
narrates an already-computed drift into a Bosnian "Na provjeri" warning. The auditor
never changes behaviour on its own — it raises a visible, append-only decision and the
owner resolves it: Undo (stop suppressing) or Zadrži (keep, logged).

Expiry also lives here: rules past expires_at stop suppressing, are visibly marked
'expired', and threshold rules restore the original config value.
"""

import logging
from collections.abc import Mapping
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.audit.decision import log_decision
from valeri_api.config import get_settings
from valeri_api.llm.client import LLMClient
from valeri_api.llm.masking import MaskingContext, rehydrate
from valeri_api.llm.prompts import AUDIT_SUMMARY_SYSTEM_PROMPT
from valeri_api.llm.schemas import NarrationFailed
from valeri_api.llm.structured import narrate_structured
from valeri_api.rules.engine import load_rule_config
from valeri_api.selfconfig.applier import (
    find_apply_decision_id,
    find_open_flag,
    restore_threshold_value,
)
from valeri_api.selfconfig.schemas import AuditResult, AuditSummaryText, DriftReport

logger = logging.getLogger("valeri.selfconfig.auditor")


# ── expiry ────────────────────────────────────────────────────────────────────


def expire_rules(session: Session) -> list[int]:
    """Mark active rules past expires_at as 'expired'; each writes a reactivation decision.

    Threshold rules restore the original rule_config value (the same restore as Undo).
    Runs at the start of every scan so an expired rule never suppresses an extra day.
    """
    rows = session.execute(
        text(
            "UPDATE app.learned_rule SET status = 'expired' "
            "WHERE status = 'active' AND expires_at IS NOT NULL AND expires_at <= now() "
            "RETURNING id, rule_type, scope, description"
        )
    ).all()

    expired_ids: list[int] = []
    for row in rows:
        payload: dict[str, Any] = {"learned_rule_id": row.id, "expired": True}
        if row.rule_type == "threshold":
            apply_decision_id = find_apply_decision_id(session, row.id)
            if apply_decision_id is not None:
                restored = restore_threshold_value(session, row.scope, apply_decision_id)
                if restored is not None:
                    payload["restored_value"] = restored
        log_decision(
            session,
            kind="reactivation",
            actor="valeri",
            summary=f"Pravilo je isteklo i više ne potiskuje signale: {row.description}",
            payload=payload,
            # Expiry follows the rule's own end date; re-learning creates a new rule.
            reversible=False,
        )
        expired_ids.append(row.id)

    if expired_ids:
        session.flush()
        logger.info("expired %d learned rule(s): %s", len(expired_ids), expired_ids)
    return expired_ids


# ── drift detection (pure SQL/Python over stored evidence) ────────────────────


def _evidence_ratio(evidence: Mapping[str, Any] | None) -> float | None:
    """The comparable 'how bad is it' ratio from stored evidence (smaller = worse)."""
    if not evidence:
        return None
    try:
        if evidence.get("ratio") is not None:
            return float(evidence["ratio"])
        value, baseline = evidence.get("value"), evidence.get("baseline")
        if value is not None and baseline is not None and float(baseline) != 0:
            return float(value) / float(baseline)
    except (TypeError, ValueError):
        return None
    return None


def _evidence_gap(evidence: Mapping[str, Any] | None) -> float | None:
    """Gap-based evidence (lost article / sleeping customer): days since last order."""
    if not evidence:
        return None
    try:
        gap = evidence.get("gap_days")
        return float(gap) if gap is not None else None
    except (TypeError, ValueError):
        return None


def compute_drift(
    session: Session, rule_row: Mapping[str, Any], config: dict[str, Any]
) -> DriftReport | None:
    """Drift check for one active suppress rule. Returns None when the stream is stable.

    Value drift: the suppressed signal's current metric vs. the rule's source signal
    (the state the owner dismissed). Volume drift: actual hits vs. the predicted blast
    radius. Both are SQL/Python over DB values — never a model guess.
    """
    drift_threshold = float(config["audit_drift_factor"])
    volume_factor = float(config["audit_volume_factor"])

    row = (
        session.execute(
            text(
                "SELECT supp.id AS suppressed_signal_id, supp.rule, supp.customer_id, "
                "       supp.evidence AS current_evidence, "
                "       c.name AS customer_name, c.segment, "
                "       src.evidence AS baseline_evidence, "
                "       (SELECT COUNT(*) FROM app.suppression_hit h "
                "        WHERE h.learned_rule_id = :rule_id) AS hits "
                "FROM app.suppression_hit h "
                "JOIN app.signal supp ON supp.id = h.signal_id "
                "LEFT JOIN core.customer c ON c.id = supp.customer_id "
                "LEFT JOIN app.signal src ON src.id = :source_signal_id "
                "WHERE h.learned_rule_id = :rule_id "
                "ORDER BY h.id DESC LIMIT 1"
            ),
            {"rule_id": rule_row["id"], "source_signal_id": rule_row["source_signal_id"]},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None

    common = {
        "learned_rule_id": rule_row["id"],
        "rule": row["rule"],
        "customer_id": row["customer_id"],
        "customer_name": row["customer_name"],
        "segment": row["segment"],
        "suppressed_signal_id": row["suppressed_signal_id"],
    }

    # ── value drift (needs a source-signal baseline; free-text rules skip this) ──
    baseline = _evidence_ratio(row["baseline_evidence"])
    current = _evidence_ratio(row["current_evidence"])
    if baseline is not None and current is not None and baseline > 0:
        factor = current / baseline
        if factor <= drift_threshold:
            return DriftReport(
                drift_kind="value",
                baseline_value=baseline,
                current_value=current,
                drift_factor=factor,
                **common,
            )

    # Gap-based rules (lost article / sleeping): a growing gap is "worse".
    baseline_gap = _evidence_gap(row["baseline_evidence"])
    current_gap = _evidence_gap(row["current_evidence"])
    if baseline_gap is not None and current_gap is not None and current_gap > 0:
        factor = baseline_gap / current_gap
        if factor <= drift_threshold:
            return DriftReport(
                drift_kind="value",
                baseline_value=baseline_gap,
                current_value=current_gap,
                drift_factor=factor,
                **common,
            )

    # ── volume drift: hiding far more than was predicted at apply time ──────────
    predicted = int((rule_row["effect_estimate"] or {}).get("total_signals") or 0)
    actual_hits = int(row["hits"])
    if actual_hits >= volume_factor * max(1, predicted):
        return DriftReport(
            drift_kind="volume",
            predicted_signals=predicted,
            actual_hits=actual_hits,
            **common,
        )

    return None


def _worse_than_kept(
    drift: DriftReport, kept_payload: Mapping[str, Any], config: dict[str, Any]
) -> bool:
    """After a Zadrži, re-flag only when drift materially worsened beyond the kept state."""
    drift_threshold = float(config["audit_drift_factor"])
    volume_factor = float(config["audit_volume_factor"])

    if drift.drift_kind == "value":
        kept_factor = kept_payload.get("drift_factor_at_keep")
        if kept_factor is None:
            return True
        return (
            drift.drift_factor is not None
            and drift.drift_factor <= float(kept_factor) * drift_threshold
        )

    kept_hits = kept_payload.get("actual_hits_at_keep")
    if kept_hits is None:
        return True
    return drift.actual_hits is not None and drift.actual_hits >= volume_factor * max(
        1, int(kept_hits)
    )


# ── the auditor run ───────────────────────────────────────────────────────────


def audit_suppressions(session: Session, client: LLMClient | None = None) -> AuditResult:
    """One auditor run: expire → drift-check every active suppress rule with enough hits.

    Raises at most one open Na provjeri flag per rule; never changes rule behaviour.
    """
    result = AuditResult()
    result.expired_rule_ids = expire_rules(session)

    config = load_rule_config(session, "selfconfig")
    min_hits = int(config["audit_min_hits"])

    rules = (
        session.execute(
            text(
                "SELECT lr.id, lr.source_signal_id, lr.description, lr.effect_estimate, "
                "       (SELECT COUNT(*) FROM app.suppression_hit h "
                "        WHERE h.learned_rule_id = lr.id) AS hits "
                "FROM app.learned_rule lr "
                "WHERE lr.status = 'active' AND lr.rule_type = 'suppress' "
                "ORDER BY lr.id"
            )
        )
        .mappings()
        .all()
    )

    for rule_row in rules:
        if int(rule_row["hits"]) < min_hits:
            continue

        flag_state = find_open_flag(session, rule_row["id"])
        if flag_state is not None and flag_state["resolution"] is None:
            # An unresolved flag already exists — never nag with duplicates.
            result.skipped_already_flagged += 1
            continue

        result.rules_checked += 1
        drift = compute_drift(session, rule_row, config)
        if drift is None:
            continue

        # Resolved by Zadrži: only re-flag when drift worsened beyond the accepted state.
        if (
            flag_state is not None
            and flag_state["resolution"] is not None
            and flag_state["resolution"]["kind"] == "approval"
            and not _worse_than_kept(drift, flag_state["resolution"]["payload"] or {}, config)
        ):
            continue

        _raise_flag(session, rule_row, drift, client)
        result.flagged.append(drift)

    session.flush()
    logger.info(
        "audit done: %d checked, %d flagged, %d skipped (already flagged), %d expired",
        result.rules_checked,
        len(result.flagged),
        result.skipped_already_flagged,
        len(result.expired_rule_ids),
    )
    return result


# ── the Na provjeri decision (visible, append-only) ───────────────────────────


def _raise_flag(
    session: Session,
    rule_row: Mapping[str, Any],
    drift: DriftReport,
    client: LLMClient | None,
) -> None:
    """Write the Na provjeri decision: Tier-1 Bosnian summary with a template fallback."""
    summary = _narrate_flag(session, drift, client)
    payload = drift.model_dump()
    payload["review"] = True
    log_decision(
        session,
        kind="reactivation",
        actor="valeri",
        summary=summary,
        payload=payload,
        reversible=True,  # resolvable: the owner keeps (Zadrži) or undoes the rule
    )


def _narrate_flag(session: Session, drift: DriftReport, client: LLMClient | None) -> str:
    """The flag summary: masked Tier-1 narration, rehydrated for humans; template fallback."""
    template = _template_flag_summary(drift)

    narration_active = client is not None or get_settings().llm_narration_enabled
    if not narration_active:
        return template

    # Mask before the prompt (principle 6): pseudonym + segment + SQL-computed numbers only.
    context = MaskingContext()
    masked_payload: dict[str, Any] = {
        "potisnuto_pravilo": drift.rule,
        "segment": drift.segment,
        "vrsta_promjene": drift.drift_kind,
        "vrijednost_pri_potiskivanju": drift.baseline_value,
        "trenutna_vrijednost": drift.current_value,
        "faktor_promjene": drift.drift_factor,
        "broj_potisnutih_signala": drift.actual_hits,
        "predvidjeno_signala": drift.predicted_signals,
    }
    if drift.customer_id is not None:
        masked_payload["kupac"] = context.register_customer(
            drift.customer_id, drift.customer_name or ""
        )

    try:
        narration, _, _ = narrate_structured(
            session,
            masked_payload,
            AuditSummaryText,
            system_prompt=AUDIT_SUMMARY_SYSTEM_PROMPT,
            instruction=(
                "Napiši kratko upozorenje vlasniku da se potisnuti obrazac značajno "
                "promijenio i da je pravilo na provjeri."
            ),
            client=client,
            register="analiza",
        )
        return rehydrate(narration.text, context)
    except NarrationFailed as failure:
        logger.warning("audit flag narration failed (%s); using the template", failure.reason)
        return template


def _template_flag_summary(drift: DriftReport) -> str:
    """Deterministic Bosnian fallback — pure formatting of SQL values (human-facing)."""
    who = f" za kupca {drift.customer_name}" if drift.customer_name else ""
    if drift.drift_kind == "value":
        return (
            f"Na provjeri: potisnuti obrazac ({drift.rule}){who} se značajno pogoršao — "
            f"odnos je pao sa {drift.baseline_value:.2f} na {drift.current_value:.2f}. "
            f"Provjerite da li pravilo treba zadržati ili poništiti."
        )
    return (
        f"Na provjeri: pravilo je potisnulo {drift.actual_hits} signala{who}, a predviđeno je "
        f"bilo {drift.predicted_signals}. Provjerite da li pravilo treba zadržati ili poništiti."
    )
