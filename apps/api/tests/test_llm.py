"""M6 unit tests: masking, prompts, validators, retry loop, disabled mode."""

import json
import os

import pytest

from valeri_api.llm.masking import (
    REDACTED_TOKEN,
    MaskingContext,
    build_masked_payload,
    collect_allowed_numbers,
    mask_text,
    pseudonym,
    redact_unresolved_names,
    rehydrate,
)
from valeri_api.llm.prompts import SYSTEM_PROMPT, narration_prompt
from valeri_api.llm.validators import (
    NarrationInvalid,
    check_number_contract,
    extract_numbers,
    parse_narration,
)

# ── masking ──────────────────────────────────────────────────────────────────


def test_pseudonym_stable_and_salted() -> None:
    """Same customer -> same pseudonym; different salt -> different pseudonym."""
    first = pseudonym(42, salt="salt-a")
    second = pseudonym(42, salt="salt-a")
    other_salt = pseudonym(42, salt="salt-b")
    other_customer = pseudonym(43, salt="salt-a")

    assert first == second
    assert first != other_salt
    assert first != other_customer
    assert first.startswith("Kupac-") and len(first) == len("Kupac-") + 6


def test_masked_payload_strips_all_pii() -> None:
    """The payload carries pseudonym + segment + evidence; never names/contacts."""
    evidence = {
        "metric": "turnover_60d",
        "value": "14155.90",
        "baseline": "31660.97",
        # Defensive case: even if PII keys sneak into evidence, they are scrubbed.
        "contact": {"name": "Amir Hodžić", "email": "amir@example.ba", "phone": "+387 61 111 222"},
        "name": "Hotel Stari Grad — restoran",
    }
    payload, context = build_masked_payload(
        rule="customer_decline",
        evidence=evidence,
        customer_id=7,
        customer_name="Hotel Stari Grad — restoran",
        segment="hotel",
    )

    serialized = json.dumps(payload, ensure_ascii=False)
    assert "Hotel Stari Grad" not in serialized
    assert "Amir" not in serialized and "amir@example.ba" not in serialized
    assert "+387" not in serialized
    assert payload["kupac"].startswith("Kupac-")
    assert payload["segment"] == "hotel"
    assert payload["podaci"]["value"] == "14155.90"
    assert context.pseudonyms[payload["kupac"]] == "Hotel Stari Grad — restoran"


def test_rehydrate_restores_names() -> None:
    context = MaskingContext()
    alias = context.register_customer(7, "Hotel Stari Grad — restoran")
    narration = f"Kupac {alias} je smanjio narudžbe. Kontaktirati {alias} ove sedmice."
    restored = rehydrate(narration, context)
    assert alias not in restored
    assert restored.count("Hotel Stari Grad — restoran") == 2


# ── unresolved-name redaction (M10 hardening, principle 6) ────────────────────


def test_unresolved_names_are_redacted() -> None:
    """A name-like span that did NOT resolve never reaches a prompt in plaintext."""
    # Mid-sentence capitalised single word = unresolved name.
    assert "Fupupu" not in redact_unresolved_names("kupac Fupupu kasni s plaćanjem")
    # Multi-word capitalised run = unresolved name, even at sentence start.
    redacted = redact_unresolved_names("Hotel Hilltop ne treba signal.")
    assert "Hilltop" not in redacted and "Hotel" not in redacted
    assert REDACTED_TOKEN in redacted
    # Trailing punctuation survives so the sentence still reads.
    assert redact_unresolved_names("Ne prijavljuj za Hotel Hilltop.").endswith(".")


def test_ordinary_sentences_pass_through_redaction() -> None:
    """Sentence capitalisation, acronyms and pseudonyms are never redacted."""
    assert (
        redact_unresolved_names("Kafići su sezonski, nemoj ih prijavljivati.")
        == "Kafići su sezonski, nemoj ih prijavljivati."
    )
    assert redact_unresolved_names("To je sezonski kupac, ne treba signal.").startswith("To je")
    # Allow-listed tokens (currency/product) survive mid-sentence.
    assert "KM" in redact_unresolved_names("promet od 5000 KM mjesečno")
    assert "VALERI" in redact_unresolved_names("zašto je VALERI ovo prijavio")
    # A new sentence after a name does not get swallowed by the run.
    redacted = redact_unresolved_names("Zanemari Fupupu. Kasni s plaćanjem.")
    assert "Kasni s plaćanjem." in redacted and "Fupupu" not in redacted


def test_mask_text_masks_resolved_and_redacts_unresolved() -> None:
    """mask_text: resolved names → pseudonyms; unresolved name-like spans → redacted."""
    context = MaskingContext()
    masked = mask_text(
        "Uporedi Hotel Stari Grad i Hotel Hilltop po prometu.",
        [("Hotel Stari Grad", 7, "Hotel Stari Grad")],
        context,
    )
    alias = pseudonym(7)
    assert alias in masked  # resolved → pseudonym (never redacted)
    assert "Stari Grad" not in masked
    assert "Hilltop" not in masked  # unresolved → redacted
    assert REDACTED_TOKEN in masked


# ── numbers ──────────────────────────────────────────────────────────────────


def test_number_extraction_and_contract() -> None:
    allowed = collect_allowed_numbers(
        {"value": "14155.90", "baseline": "31660.97", "delta_pct": "-55.3", "gap_days": 126}
    )

    # Numbers from the evidence pass (both dot and comma forms, with/without sign).
    ok_body = "Promet je 14155.90 KM umjesto 31660.97 KM, pad od 55.3%. Pauza traje 126 dana."
    assert check_number_contract(ok_body, allowed) == []
    comma_body = "Promet je 14155,90 KM (pad 55,3%)."
    assert check_number_contract(comma_body, allowed) == []

    # Invented numbers are flagged.
    bad_body = "Promet je oko 15000 KM, što je pad od 50%."
    violations = check_number_contract(bad_body, allowed)
    assert "15000" in violations and "50" in violations

    assert extract_numbers("12.5% i 3 komada") == ["12.5", "3"]


# ── prompts ──────────────────────────────────────────────────────────────────


def test_prompt_contains_only_finished_numbers() -> None:
    """The prompt embeds evidence verbatim and never asks the model to compute."""
    payload = {"signal": "customer_decline", "kupac": "Kupac-abc123", "podaci": {"value": "100.00"}}
    prompt = narration_prompt(payload)

    assert '"value": "100.00"' in prompt
    assert "Kupac-abc123" in prompt
    for forbidden in ("izračunaj", "saberi", "procijeni", "calculate", "compute"):
        assert forbidden not in prompt.lower()
    # The system prompt explicitly forbids computing.
    assert "NIKAD ne računaj" in SYSTEM_PROMPT


# ── validators ───────────────────────────────────────────────────────────────


def test_parse_narration_rejects_bad_output() -> None:
    with pytest.raises(NarrationInvalid):
        parse_narration("nema jsona ovdje")
    with pytest.raises(NarrationInvalid):
        parse_narration('{"body": "prekratko", "register": "analiza", "confidence": 0.5}')
    with pytest.raises(NarrationInvalid):
        parse_narration(
            '{"body": "dovoljno dugačak tekst za validaciju šeme", '
            '"register": "nepostojeći", "confidence": 0.5}'
        )
    with pytest.raises(NarrationInvalid):
        parse_narration(
            '{"body": "dovoljno dugačak tekst za validaciju šeme", '
            '"register": "analiza", "confidence": 1.5}'
        )

    narration = parse_narration(
        'Evo odgovora: {"body": "Kupac-abc je smanjio narudžbe; preporučujem kontakt.", '
        '"register": "preporuka", "confidence": 0.8} hvala'
    )
    assert narration.register == "preporuka"


# ── retry loop + disabled mode (use the contract-test fake) ──────────────────


def test_reject_retry_loop(db_engine, seed_data) -> None:
    """Invalid then valid -> success with 2 ai_log rows; feedback prompt carries errors."""
    import datetime

    from sqlalchemy import text
    from sqlalchemy.orm import Session

    from tests.test_llm_contract import FakeLLMClient, good_narration_json
    from valeri_api.llm.narration import narrate_task
    from valeri_api.scanner.scan import run_scan
    from valeri_api.seed.loader import load, reset

    as_of = datetime.date.fromisoformat(seed_data.manifest["as_of"])
    with Session(db_engine) as session:
        session.execute(
            text(
                "TRUNCATE audit.ai_log, audit.task_log, app.task_feedback, app.task, "
                "app.signal, app.learned_rule RESTART IDENTITY CASCADE"
            )
        )
        reset(session)
        load(seed_data, session)
        run_scan(session, as_of=as_of, create_tasks=False)

        signal = session.execute(
            text(
                "SELECT s.id, s.rule, s.evidence, s.customer_id, c.name AS customer_name "
                "FROM app.signal s JOIN core.customer c ON c.id = s.customer_id LIMIT 1"
            )
        ).one()

        fake = FakeLLMClient(["pokvaren odgovor", good_narration_json(signal.evidence)])
        result = narrate_task(
            session,
            rule=signal.rule,
            evidence=signal.evidence,
            customer_id=signal.customer_id,
            customer_name=signal.customer_name,
            segment=None,
            client=fake,
        )
        assert result.attempts == 2

        # The retry prompt fed the validation errors back to the model.
        retry_prompt = fake.captured[1]["user"]
        assert "ODBIJEN" in retry_prompt

        n_logs = session.execute(text("SELECT COUNT(*) FROM audit.ai_log")).scalar()
        assert n_logs == 2

        session.rollback()
        reset(session)
        load(seed_data, session)
        session.commit()


def test_narration_disabled_uses_templates(db_engine, seed_data, monkeypatch) -> None:
    """llm_narration_enabled=False -> no LLM calls, no ai_log rows, template bodies."""
    import datetime

    from sqlalchemy import text
    from sqlalchemy.orm import Session

    from valeri_api.config import get_settings
    from valeri_api.db import get_engine
    from valeri_api.scanner.scan import run_scan
    from valeri_api.seed.loader import load, reset
    from valeri_api.signals.pipeline import create_tasks_from_signals

    monkeypatch.setenv("LLM_NARRATION_ENABLED", "false")
    get_settings.cache_clear()
    get_engine.cache_clear()

    as_of = datetime.date.fromisoformat(seed_data.manifest["as_of"])
    with Session(db_engine) as session:
        session.execute(
            text(
                "TRUNCATE audit.ai_log, audit.task_log, app.task_feedback, app.task, "
                "app.signal, app.learned_rule RESTART IDENTITY CASCADE"
            )
        )
        reset(session)
        load(seed_data, session)
        run_scan(session, as_of=as_of, create_tasks=False)
        result = create_tasks_from_signals(session, as_of=as_of)

        assert result.created > 0
        n_logs = session.execute(text("SELECT COUNT(*) FROM audit.ai_log")).scalar()
        assert n_logs == 0, "narration disabled must mean zero LLM calls"

        n_template = session.execute(
            text("SELECT COUNT(*) FROM app.task WHERE body LIKE '%Brojke iz baze · SQL%'")
        ).scalar()
        assert n_template == result.created

        session.rollback()
        reset(session)
        load(seed_data, session)
        session.commit()


# ── optional live smoke test ──────────────────────────────────────────────────


@pytest.mark.skipif(
    not os.environ.get("LITELLM_SMOKE_TEST"),
    reason="set LITELLM_SMOKE_TEST=1 with a reachable LiteLLM gateway to run",
)
def test_live_gateway_smoke() -> None:  # pragma: no cover
    """One real narration through LiteLLM -> valid schema. Runs only on-prem."""
    from valeri_api.llm.client import get_llm_client
    from valeri_api.llm.prompts import SYSTEM_PROMPT, narration_prompt
    from valeri_api.llm.validators import parse_narration

    client = get_llm_client()
    payload = {
        "signal": "customer_decline",
        "kupac": "Kupac-test01",
        "segment": "hotel",
        "podaci": {"value": "450.00", "baseline": "1000.00", "delta_pct": "-55.0"},
    }
    response = client.complete(SYSTEM_PROMPT, narration_prompt(payload))
    narration = parse_narration(response.text)
    assert narration.register in ("analiza", "preporuka", "akcija")
