"""Contract / RBAC / logging / decision tests for propose_rule_change (M10, per /tool).

The catalog's second mutation: feedback → structured rule change → graduated
autonomy. The /tool mutation contract: an auto-applied rule writes a reversible
app.decision; a pending rule writes NOTHING until confirmed; the blast radius
(effect estimate) comes from SQL; every call is logged.

All LLM interaction uses the scripted fake from tests/test_selfconfig.py.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.test_selfconfig import ProposerFakeLLMClient, category_proposal, entity_proposal
from tests.tools.conftest import tool_log_rows
from valeri_api.auth.models import AppUser
from valeri_api.tools.base import ToolContext
from valeri_api.tools.catalog import dispatch


def _patch_llm(monkeypatch, proposal: dict) -> ProposerFakeLLMClient:
    """The tool path uses the production client factory → patch it with a scripted fake."""
    fake = ProposerFakeLLMClient(proposal)
    monkeypatch.setattr("valeri_api.llm.structured.get_llm_client", lambda: fake)
    return fake


def _tasked_decline_signal(session: Session):
    return session.execute(
        text(
            "SELECT id, customer_id FROM app.signal "
            "WHERE rule = 'customer_decline' AND status = 'tasked' ORDER BY id LIMIT 1"
        )
    ).one()


def _rep_context_with_signal(tool_session: Session) -> tuple[ToolContext, int, int]:
    """A rep login that owns a tasked signal + that signal + a foreign signal."""
    row = tool_session.execute(
        text(
            "SELECT s.id AS signal_id, au.id AS user_id, cur.sales_rep_id "
            "FROM app.signal s "
            "JOIN ("
            "  SELECT DISTINCT ON (customer_id) customer_id, sales_rep_id "
            "  FROM core.customer_rep ORDER BY customer_id, from_date DESC"
            ") cur ON cur.customer_id = s.customer_id "
            "JOIN app.app_user au ON au.sales_rep_id = cur.sales_rep_id "
            "WHERE s.status = 'tasked' ORDER BY s.id LIMIT 1"
        )
    ).one()
    rep_user = tool_session.query(AppUser).filter(AppUser.id == row.user_id).one()
    foreign_signal = tool_session.execute(
        text(
            "SELECT s.id FROM app.signal s "
            "JOIN ("
            "  SELECT DISTINCT ON (customer_id) customer_id, sales_rep_id "
            "  FROM core.customer_rep ORDER BY customer_id, from_date DESC"
            ") cur ON cur.customer_id = s.customer_id "
            "WHERE cur.sales_rep_id != :rep_id AND s.status = 'tasked' ORDER BY s.id LIMIT 1"
        ),
        {"rep_id": row.sales_rep_id},
    ).scalar()
    context = ToolContext(session=tool_session, user=rep_user)
    return context, row.signal_id, foreign_signal


# ── the mutation contract ─────────────────────────────────────────────────────


def test_narrow_proposal_auto_applies_with_reversible_decision(owner_context, monkeypatch) -> None:
    """Entity-scoped dismissal → active rule + exactly one reversible decision (actor=valeri)."""
    session = owner_context.session
    _patch_llm(monkeypatch, entity_proposal())
    signal = _tasked_decline_signal(session)

    result = dispatch(
        owner_context,
        "propose_rule_change",
        {"reason": "To je sezonski kupac, ne treba signal.", "signal_id": signal.id},
    )
    assert result.ok, result.error
    assert result.output["applied"] is True
    assert result.output["requires_confirm"] is False
    assert result.output["register"] == "akcija"

    # The learned rule is active with the REAL customer id (resolved server-side).
    rule = session.execute(
        text("SELECT status, autonomy, scope FROM app.learned_rule WHERE id = :id"),
        {"id": result.output["learned_rule_id"]},
    ).one()
    assert rule.status == "active"
    assert rule.autonomy == "auto_applied"
    assert rule.scope["entity_id"] == signal.customer_id

    # Exactly one reversible decision (the /tool mutation contract).
    decisions = session.execute(
        text("SELECT kind, actor, reversible FROM app.decision ORDER BY id")
    ).all()
    assert len(decisions) == 1
    assert decisions[0].kind == "suppression"
    assert decisions[0].actor == "valeri"
    assert decisions[0].reversible is True
    assert result.output["decision_id"] is not None


def test_broad_proposal_requires_confirm_and_writes_nothing(owner_context, monkeypatch) -> None:
    """Category scope → pending_confirm, NO decision, the scanner ignores it."""
    session = owner_context.session
    _patch_llm(monkeypatch, category_proposal())
    signal = _tasked_decline_signal(session)

    result = dispatch(
        owner_context,
        "propose_rule_change",
        {"reason": "Svi kafići su sezonski, nemoj ih prijavljivati.", "signal_id": signal.id},
    )
    assert result.ok, result.error
    assert result.output["applied"] is False
    assert result.output["requires_confirm"] is True
    assert result.output["register"] == "preporuka"
    assert result.output["decision_id"] is None

    rule_status = session.execute(
        text("SELECT status FROM app.learned_rule WHERE id = :id"),
        {"id": result.output["learned_rule_id"]},
    ).scalar()
    assert rule_status == "pending_confirm"
    assert session.execute(text("SELECT COUNT(*) FROM app.decision")).scalar() == 0

    from valeri_api.rules.engine import load_active_suppressions

    assert load_active_suppressions(session) == []


def test_effect_estimate_matches_sql(owner_context, monkeypatch) -> None:
    """The blast radius the tool reports equals a direct SQL count (numbers contract)."""
    session = owner_context.session
    _patch_llm(monkeypatch, entity_proposal())
    signal = _tasked_decline_signal(session)

    result = dispatch(
        owner_context,
        "propose_rule_change",
        {"reason": "Sezonski kupac.", "signal_id": signal.id},
    )
    assert result.ok, result.error
    effect = result.output["effect_estimate"]

    sql_count = session.execute(
        text(
            "SELECT COUNT(*) FROM app.signal "
            "WHERE customer_id = :cid AND rule = 'customer_decline' "
            "AND created_at > now() - make_interval(days => :window)"
        ),
        {"cid": signal.customer_id, "window": effect["window_days"]},
    ).scalar()
    assert effect["total_signals"] == sql_count


# ── RBAC ──────────────────────────────────────────────────────────────────────


def test_rbac_rep_own_signal_only(tool_session, monkeypatch) -> None:
    """A rep may propose for their own customer's signal; a foreign signal is forbidden."""
    _patch_llm(monkeypatch, entity_proposal())
    rep_context, own_signal, foreign_signal = _rep_context_with_signal(tool_session)

    allowed = dispatch(
        rep_context,
        "propose_rule_change",
        {"reason": "Sezonski kupac, ne treba signal.", "signal_id": own_signal},
    )
    assert allowed.ok, allowed.error

    blocked = dispatch(
        rep_context,
        "propose_rule_change",
        {"reason": "Tuđi kupac.", "signal_id": foreign_signal},
    )
    assert not blocked.ok
    assert blocked.error_code == "forbidden"


def test_rbac_rep_cannot_propose_free_text(tool_session, monkeypatch) -> None:
    """General (no-signal) proposals can affect many customers → owner/admin only."""
    _patch_llm(monkeypatch, category_proposal())
    rep_context, _, _ = _rep_context_with_signal(tool_session)

    result = dispatch(
        rep_context,
        "propose_rule_change",
        {"reason": "Nemoj prijavljivati kafiće."},
    )
    assert not result.ok
    assert result.error_code == "forbidden"

    # Nothing was created.
    assert tool_session.execute(text("SELECT COUNT(*) FROM app.learned_rule")).scalar() == 0


def test_rbac_finance_blocked(finance_context) -> None:
    """Finance never manages rules — the role gate rejects before anything runs (no LLM)."""
    result = dispatch(
        finance_context,
        "propose_rule_change",
        {"reason": "Finansije ne predlažu pravila."},
    )
    assert not result.ok
    assert result.error_code == "forbidden"

    session = finance_context.session
    assert session.execute(text("SELECT COUNT(*) FROM app.learned_rule")).scalar() == 0
    assert session.execute(text("SELECT COUNT(*) FROM app.decision")).scalar() == 0


# ── logging ───────────────────────────────────────────────────────────────────


def test_every_call_logged(owner_context, finance_context, monkeypatch) -> None:
    """Success and denial both land in tool_call_log (the audit trail is total)."""
    session = owner_context.session
    _patch_llm(monkeypatch, entity_proposal())
    signal = _tasked_decline_signal(session)

    before = len(tool_log_rows(session, "propose_rule_change"))
    dispatch(
        owner_context,
        "propose_rule_change",
        {"reason": "Sezonski kupac.", "signal_id": signal.id},
    )
    dispatch(finance_context, "propose_rule_change", {"reason": "Odbijeno."})

    rows = tool_log_rows(session, "propose_rule_change")
    assert len(rows) == before + 2
    assert [row.ok for row in rows[-2:]] == [True, False]
