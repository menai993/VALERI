"""M6 acceptance contracts (TDD: written before the narration implementation).

1. LLM output validates against the schema (reject + retry, never raw).
2. Rendered numbers EQUAL the SQL numbers (number contract, mechanically enforced).
3. NO raw PII appears in any prompt or in audit.ai_log.masked_input.
Plus: graceful template fallback and ai_log one-row-per-call granularity.

All tests use FakeLLMClient — no real API calls, no gateway needed.
"""

import datetime
import json
import re

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from valeri_api.llm.client import LLMResponse, LLMUnavailable
from valeri_api.scanner.scan import run_scan
from valeri_api.signals.pipeline import create_tasks_from_signals

# ── the fake client ───────────────────────────────────────────────────────────


class FakeLLMClient:
    """Scripted LLM double: returns queued responses and captures every prompt."""

    def __init__(self, responses: list[str | Exception] | None = None) -> None:
        self.responses = list(responses or [])
        self.captured: list[dict[str, str]] = []  # every (system, user) pair sent
        self.model = "fake-tier1"

    def complete(self, system: str, user: str) -> LLMResponse:
        self.captured.append({"system": system, "user": user})
        if not self.responses:
            raise AssertionError("FakeLLMClient ran out of scripted responses")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        # Mimic a real LLM following instructions: echo the pseudonym from the prompt
        # wherever the scripted response says {{KUPAC}}.
        pseudonym_match = re.search(r"Kupac-[0-9a-f]{6}", user)
        if pseudonym_match:
            item = item.replace("{{KUPAC}}", pseudonym_match.group(0))
        return LLMResponse(text=item, model=self.model, tokens=100, latency_ms=50)


def good_narration_json(evidence: dict) -> str:
    """A valid narration whose numbers all come from the given evidence.

    The body references {{KUPAC}} — the fake client substitutes the pseudonym it
    finds in the prompt (mimicking a real LLM that follows the system prompt).
    """
    value = evidence.get("value") or evidence.get("gap_days") or ""
    baseline = evidence.get("baseline") or evidence.get("avg_order_interval_d") or ""
    body = (
        f"{{{{KUPAC}}}} pokazuje promjenu u kupovini. "
        f"Vrijednost iz baze: {value} KM, uobičajeni nivo {baseline} KM. "
        f"Preporučuje se kontakt s kupcem u najkraćem roku."
    )
    return json.dumps(
        {"body": body, "register": "preporuka", "confidence": 0.85}, ensure_ascii=False
    )


# ── fixtures ─────────────────────────────────────────────────────────────────


def _reset_app_tables(session: Session) -> None:
    session.execute(
        text(
            "TRUNCATE audit.ai_log, audit.task_log, app.task_feedback, app.task, app.signal, "
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


@pytest.fixture
def scanned_session(db_engine: Engine, seed_data):
    """Seed + signals (no tasks yet); yields an open session; restores seed after."""
    from valeri_api.seed.loader import load, reset

    as_of = datetime.date.fromisoformat(seed_data.manifest["as_of"])
    session = Session(db_engine)
    _reset_app_tables(session)
    reset(session)
    load(seed_data, session)
    run_scan(session, as_of=as_of, create_tasks=False)
    session.commit()

    yield session, as_of

    session.rollback()
    session.close()
    _restore_seed(db_engine, seed_data)


def _signal_rows(session: Session) -> list:
    return session.execute(
        text(
            "SELECT s.id, s.rule, s.evidence, s.customer_id, c.name AS customer_name "
            "FROM app.signal s LEFT JOIN core.customer c ON c.id = s.customer_id "
            "WHERE s.status = 'new' ORDER BY s.id"
        )
    ).all()


# ── contract 1: schema validation with reject + retry ───────────────────────


def test_contract_output_validates_against_schema(scanned_session) -> None:
    """Malformed output is rejected and retried; persistent failure -> NarrationFailed."""
    from valeri_api.llm.narration import narrate_task
    from valeri_api.llm.schemas import NarrationFailed, NarrationResult

    session, _ = scanned_session
    signal = _signal_rows(session)[0]

    # a) Bad JSON then good JSON -> succeeds on retry (attempts == 2).
    fake = FakeLLMClient(
        ["ovo nije json", good_narration_json(signal.evidence)],
    )
    result = narrate_task(
        session,
        rule=signal.rule,
        evidence=signal.evidence,
        customer_id=signal.customer_id,
        customer_name=signal.customer_name,
        segment=None,
        client=fake,
    )
    assert isinstance(result, NarrationResult)
    assert result.attempts == 2
    assert result.narration.register in ("analiza", "preporuka", "akcija")
    assert 0 <= result.narration.confidence <= 1

    # b) Persistently bad output -> NarrationFailed (caller falls back to templates).
    always_bad = FakeLLMClient(["nije json", '{"body": "x"}', '{"register": "haos"}'])
    with pytest.raises(NarrationFailed):
        narrate_task(
            session,
            rule=signal.rule,
            evidence=signal.evidence,
            customer_id=signal.customer_id,
            customer_name=signal.customer_name,
            segment=None,
            client=always_bad,
        )


# ── contract 2: rendered numbers equal SQL numbers ───────────────────────────


def test_contract_rendered_numbers_equal_sql_numbers(scanned_session) -> None:
    """A narration with an invented number is rejected and never reaches a task body."""
    from valeri_api.llm.narration import narrate_task
    from valeri_api.llm.schemas import NarrationFailed

    session, _ = scanned_session
    signal = next(row for row in _signal_rows(session) if row.rule == "customer_decline")

    # a) Invented number -> rejected on every attempt -> NarrationFailed.
    invented = json.dumps(
        {
            "body": "Kupac je smanjio kupovinu za 99999.99 KM što je veliki pad.",
            "register": "analiza",
            "confidence": 0.9,
        },
        ensure_ascii=False,
    )
    fake = FakeLLMClient([invented, invented, invented])
    with pytest.raises(NarrationFailed):
        narrate_task(
            session,
            rule=signal.rule,
            evidence=signal.evidence,
            customer_id=signal.customer_id,
            customer_name=signal.customer_name,
            segment=None,
            client=fake,
        )

    # b) Numbers from the evidence -> accepted; every number in the body is from SQL.
    from valeri_api.llm.masking import collect_allowed_numbers
    from valeri_api.llm.validators import check_number_contract

    good = FakeLLMClient([good_narration_json(signal.evidence)])
    result = narrate_task(
        session,
        rule=signal.rule,
        evidence=signal.evidence,
        customer_id=signal.customer_id,
        customer_name=signal.customer_name,
        segment=None,
        client=good,
    )
    allowed = collect_allowed_numbers({"signal": signal.rule, "podaci": signal.evidence})
    assert check_number_contract(result.narration.body, allowed) == []


# ── contract 3: no raw PII in any prompt ─────────────────────────────────────


def test_contract_no_raw_pii_in_prompt(scanned_session, seed_data) -> None:
    """Customer names / contact data never appear in prompts or ai_log.masked_input;
    pseudonyms do; the stored human-facing task body has the real name back."""
    session, as_of = scanned_session

    # Collect all real PII from the seed: customer names + contact data.
    real_customer_names = {c["name"] for c in seed_data.customers}
    contact_pii = set()
    for contact in seed_data.contacts:
        contact_pii.add(contact["name"])
        contact_pii.add(contact["email"])
        contact_pii.add(contact["phone"])

    signals = _signal_rows(session)
    # One good scripted response per signal.
    fake = FakeLLMClient([good_narration_json(row.evidence) for row in signals])

    create_tasks_from_signals(session, as_of=as_of, client=fake)
    session.commit()

    # a) No prompt contains any real customer name or contact PII; pseudonyms appear.
    assert fake.captured, "no prompts were sent"
    all_prompts = "\n".join(item["system"] + "\n" + item["user"] for item in fake.captured)
    for name in real_customer_names:
        assert name not in all_prompts, f"customer name {name!r} leaked into a prompt"
    for pii in contact_pii:
        assert pii not in all_prompts, f"contact PII {pii!r} leaked into a prompt"
    assert "Kupac-" in all_prompts, "pseudonyms missing from prompts"

    # b) ai_log.masked_input is equally clean.
    masked_inputs = [
        json.dumps(row[0], ensure_ascii=False)
        for row in session.execute(text("SELECT masked_input FROM audit.ai_log"))
    ]
    assert masked_inputs
    for masked in masked_inputs:
        for name in real_customer_names:
            assert name not in masked, f"customer name {name!r} leaked into ai_log"
        for pii in contact_pii:
            assert pii not in masked, f"contact PII {pii!r} leaked into ai_log"

    # c) The stored task bodies (human-facing) DO contain real names (rehydrated).
    bodies_with_real_names = session.execute(
        text(
            "SELECT COUNT(*) FROM app.task t "
            "JOIN app.signal s ON s.id = t.signal_id "
            "JOIN core.customer c ON c.id = s.customer_id "
            "WHERE POSITION(c.name IN t.body) > 0"
        )
    ).scalar()
    assert bodies_with_real_names > 0, "rehydration did not put real names into task bodies"

    # d) No task body contains a pseudonym (rehydration is complete).
    bodies_with_pseudonyms = session.execute(
        text("SELECT COUNT(*) FROM app.task WHERE body LIKE '%Kupac-%'")
    ).scalar()
    assert bodies_with_pseudonyms == 0


# ── fallback + ai_log granularity ─────────────────────────────────────────────


def test_pipeline_fallback_to_templates(scanned_session) -> None:
    """Gateway down -> tasks still created with template bodies; calls logged."""
    session, as_of = scanned_session
    n_signals = len(_signal_rows(session))

    fake = FakeLLMClient([LLMUnavailable("gateway down")] * n_signals)
    result = create_tasks_from_signals(session, as_of=as_of, client=fake)
    session.commit()

    assert result.created == n_signals, "fallback must still create every task"

    # Tasks have the template footer (the fallback body).
    n_template_bodies = session.execute(
        text("SELECT COUNT(*) FROM app.task WHERE body LIKE '%Brojke iz baze · SQL%'")
    ).scalar()
    assert n_template_bodies == n_signals

    # And the register falls back to 'preporuka'.
    registers = {row[0] for row in session.execute(text("SELECT DISTINCT register FROM app.task"))}
    assert registers == {"preporuka"}


def test_ai_log_one_row_per_call(scanned_session) -> None:
    """1 call = 1 row; a rejected attempt + a successful retry = 2 rows."""
    from valeri_api.llm.narration import narrate_task

    session, _ = scanned_session
    signal = _signal_rows(session)[0]

    # Happy path: exactly one row.
    fake_one = FakeLLMClient([good_narration_json(signal.evidence)])
    narrate_task(
        session,
        rule=signal.rule,
        evidence=signal.evidence,
        customer_id=signal.customer_id,
        customer_name=signal.customer_name,
        segment=None,
        client=fake_one,
    )
    count_after_first = session.execute(text("SELECT COUNT(*) FROM audit.ai_log")).scalar()
    assert count_after_first == 1

    # One rejection + one success: two more rows.
    fake_two = FakeLLMClient(["nije json", good_narration_json(signal.evidence)])
    narrate_task(
        session,
        rule=signal.rule,
        evidence=signal.evidence,
        customer_id=signal.customer_id,
        customer_name=signal.customer_name,
        segment=None,
        client=fake_two,
    )
    total = session.execute(text("SELECT COUNT(*) FROM audit.ai_log")).scalar()
    assert total == 3

    # Rows carry model, tokens, latency; the successful ones carry register + confidence.
    rows = session.execute(
        text("SELECT model, output, register, confidence, tokens, latency_ms FROM audit.ai_log")
    ).all()
    assert all(row.model == "fake-tier1" for row in rows)
    assert all(row.tokens is not None and row.latency_ms is not None for row in rows)
    successful = [row for row in rows if row.register is not None]
    assert len(successful) == 2
    assert all(row.confidence is not None for row in successful)
