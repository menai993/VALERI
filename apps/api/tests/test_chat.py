"""M9 acceptance: the conversation layer (Ask VALERI).

The milestone acceptance: a Bosnian question routes to query_metric/compare_periods
and returns SQL-correct numbers tagged Analiza; a rep is RBAC-blocked from finance
tools; every call is in tool_call_log. Plus: PII masking in chat, SSE contract,
session memory, fallbacks.

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
from valeri_api.conversation.answer import _knowledge_answer
from valeri_api.conversation.assistant import _assistant_template
from valeri_api.conversation.models import Conversation, Message
from valeri_api.conversation.service import handle_message
from valeri_api.llm.client import LLMResponse
from valeri_api.scanner.scan import run_scan
from valeri_api.seed.users import OWNER_EMAIL

# ── fakes ─────────────────────────────────────────────────────────────────────


class ChatFakeLLMClient:
    """One fake for both chat LLM roles, keyed off the system prompt.

    - Intent calls return the scripted intent JSON ({{KUPAC}} → the pseudonym
      found in the prompt, mimicking a model that uses given pseudonyms).
    - Answer calls echo the tool output's `value` (or no numbers at all), so the
      number contract always holds — like a rule-following model.
    """

    def __init__(self, intent: dict, proposal: dict | None = None) -> None:
        self.intent_json = json.dumps(intent, ensure_ascii=False)
        self.proposal_json = json.dumps(proposal, ensure_ascii=False) if proposal else None
        self.captured: list[dict[str, str]] = []
        self.model = "fake-tier1"

    def complete(self, system: str, user: str) -> LLMResponse:
        self.captured.append({"system": system, "user": user})
        pseudonym = re.search(r"Kupac-[0-9a-f]{6}", user)
        if "usmjerivač namjera" in system:
            text_out = self.intent_json
            if pseudonym:
                text_out = text_out.replace("{{KUPAC}}", pseudonym.group(0))
        elif "strukturator pravila" in system and self.proposal_json:
            # M10: the rule-change proposer prompt.
            text_out = self.proposal_json
            if pseudonym:
                text_out = text_out.replace("{{KUPAC}}", pseudonym.group(0))
        else:
            text_out = self._answer(user)
        return LLMResponse(text=text_out, model=self.model, tokens=100, latency_ms=50)

    def _answer(self, user: str) -> str:
        payload_start = user.find("{")
        value = None
        pseudonyms: list[str] = []
        if payload_start >= 0:
            payload_text = user[payload_start:]
            pseudonyms = re.findall(r"Kupac-[0-9a-f]{6}", payload_text)
            try:
                payload = json.loads(payload_text)
                data = payload.get("podaci", {})
                value = data.get("value") or data.get("turnover_60d")
            except json.JSONDecodeError:
                value = None

        parts = ["Prema podacima iz baze"]
        if pseudonyms:
            parts.append(f"za kupca {pseudonyms[0]}")
        if value is not None:
            parts.append(f"vrijednost iznosi {value} KM")
        parts.append("za traženi period.")
        return json.dumps({"text": ", ".join(parts), "register": "analiza"}, ensure_ascii=False)


# ── fixtures ──────────────────────────────────────────────────────────────────


def _reset_app_tables(session: Session) -> None:
    session.execute(
        text(
            "TRUNCATE audit.ai_log, audit.task_log, app.task_feedback, app.approval, "
            "app.owner_report, app.tool_call_log, app.message, app.conversation, app.decision, "
            "app.task, app.signal, app.learned_rule RESTART IDENTITY CASCADE"
        )
    )


@pytest.fixture(scope="module")
def chat_db(db_engine: Engine, seed_data):
    """Seed + signals + tasks: the data chat questions are answered from."""
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
def chat_session(chat_db):
    """A rolled-back session + owner/rep users + a fresh conversation per test."""
    engine, as_of = chat_db
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)

    owner = session.query(AppUser).filter(AppUser.email == OWNER_EMAIL).one()
    rep = session.query(AppUser).filter(AppUser.role == "sales_rep").order_by(AppUser.id).first()

    try:
        yield session, owner, rep, as_of
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


def _new_conversation(session: Session, user: AppUser) -> Conversation:
    conversation = Conversation(user_id=user.id)
    session.add(conversation)
    session.flush()
    return conversation


def _reply_text(events) -> str:
    return next(event.data["text"] for event in events if event.type == "token")


def _reply_register(events) -> str:
    return next(event.data["register"] for event in events if event.type == "register")


# ── 4. THE MILESTONE ACCEPTANCE ───────────────────────────────────────────────


def test_bosnian_question_returns_sql_numbers_tagged_analiza(chat_session) -> None:
    """'Koliki je promet u zadnjih 30 dana?' → query_metric → SQL number, register analiza."""
    session, owner, _, _ = chat_session
    today = datetime.date.today()
    from_date = today - datetime.timedelta(days=30)

    fake = ChatFakeLLMClient(
        intent={
            "intent": "question",
            "tool": "query_metric",
            "params": {"metric": "turnover", "from_date": str(from_date), "to_date": str(today)},
            "confidence": 0.95,
        }
    )

    conversation = _new_conversation(session, owner)
    events = handle_message(
        session, owner, conversation, "Koliki je promet u zadnjih 30 dana?", client=fake
    )

    # The reply contains EXACTLY the SQL-computed number.
    sql_value = session.execute(
        text(
            "SELECT COALESCE(SUM(l.line_total), 0) FROM core.invoice_line l "
            "JOIN core.invoice i ON i.id = l.invoice_id "
            "WHERE i.date > :a AND i.date <= :b"
        ),
        {"a": from_date, "b": today},
    ).scalar()

    reply = _reply_text(events)
    assert str(sql_value) in reply, f"the SQL value {sql_value} must appear in: {reply}"
    assert _reply_register(events) == "analiza"

    # The reply is persisted with its register + tool calls.
    stored = session.execute(
        text(
            "SELECT content, register, tool_calls FROM app.message "
            "WHERE conversation_id = :id AND role = 'assistant'"
        ),
        {"id": conversation.id},
    ).one()
    assert str(sql_value) in stored.content
    assert stored.register == "analiza"
    assert stored.tool_calls[0]["tool"] == "query_metric"
    assert stored.tool_calls[0]["ok"] is True


def test_compare_periods_question(chat_session) -> None:
    """A comparison question routes to compare_periods; the delta comes from SQL."""
    session, owner, _, _ = chat_session
    today = datetime.date.today()

    fake = ChatFakeLLMClient(
        intent={
            "intent": "question",
            "tool": "compare_periods",
            "params": {
                "period_a_from": str(today - datetime.timedelta(days=30)),
                "period_a_to": str(today),
                "period_b_from": str(today - datetime.timedelta(days=60)),
                "period_b_to": str(today - datetime.timedelta(days=30)),
            },
            "confidence": 0.9,
        }
    )

    conversation = _new_conversation(session, owner)
    events = handle_message(
        session, owner, conversation, "Uporedi promet ovog i prošlog mjeseca", client=fake
    )

    assert _reply_register(events) == "analiza"
    done = next(event for event in events if event.type == "done")
    assert done.data["tool_calls"][0]["tool"] == "compare_periods"
    assert done.data["tool_calls"][0]["ok"] is True


# ── 5. masking in chat ────────────────────────────────────────────────────────


def test_customer_question_resolves_and_masks(chat_session, seed_data) -> None:
    """A question naming a real customer: prompts carry pseudonyms only; reply is rehydrated."""
    session, owner, _, _ = chat_session

    # A customer with metrics (so the tool returns data).
    customer = session.execute(
        text(
            "SELECT c.id, c.name FROM core.customer c "
            "JOIN core.customer_metrics m ON m.customer_id = c.id "
            "WHERE m.turnover_60d > 0 ORDER BY c.id LIMIT 1"
        )
    ).one()

    fake = ChatFakeLLMClient(
        intent={
            "intent": "question",
            "tool": "query_metric",
            "params": {"metric": "customer_turnover_60d", "customer_ref": "{{KUPAC}}"},
            "confidence": 0.9,
        }
    )

    conversation = _new_conversation(session, owner)
    question = f"Koliki je promet kupca {customer.name} u zadnjih 60 dana?"
    events = handle_message(session, owner, conversation, question, client=fake)

    # a) No prompt contains the real customer name; pseudonyms do appear.
    all_prompts = "\n".join(item["system"] + "\n" + item["user"] for item in fake.captured)
    assert customer.name not in all_prompts, "real customer name leaked into an LLM prompt"
    assert "Kupac-" in all_prompts

    # b) audit.ai_log.masked_input is equally clean.
    masked_inputs = [
        json.dumps(row[0], ensure_ascii=False)
        for row in session.execute(text("SELECT masked_input FROM audit.ai_log"))
    ]
    assert masked_inputs
    for masked in masked_inputs:
        assert customer.name not in masked, "real customer name leaked into ai_log"

    # c) The tool received the REAL id (server-side ref resolution) and returned SQL data.
    sql_value = session.execute(
        text("SELECT turnover_60d FROM core.customer_metrics WHERE customer_id = :id"),
        {"id": customer.id},
    ).scalar()
    reply = _reply_text(events)
    assert str(sql_value) in reply

    # d) The human-facing reply has the real name back (rehydrated), no pseudonyms.
    assert customer.name in reply
    assert "Kupac-" not in reply


# ── 6. rep RBAC in chat ───────────────────────────────────────────────────────


def test_rep_blocked_from_finance_tools(chat_session) -> None:
    """A rep asking for company-wide revenue gets a refusal — no numbers, logged as denied."""
    session, _, rep, _ = chat_session
    today = datetime.date.today()

    fake = ChatFakeLLMClient(
        intent={
            "intent": "question",
            "tool": "query_metric",
            "params": {
                "metric": "turnover",
                "from_date": str(today - datetime.timedelta(days=30)),
                "to_date": str(today),
            },
            "confidence": 0.95,
        }
    )

    conversation = _new_conversation(session, rep)
    events = handle_message(
        session, rep, conversation, "Koliki je ukupan promet firme?", client=fake
    )

    reply = _reply_text(events)
    # A polite Bosnian refusal with NO numbers in it.
    assert "Nemate pristup" in reply
    assert not re.search(r"\d+[.,]\d+", reply), f"numbers leaked into the refusal: {reply}"

    # The denied call is in tool_call_log with ok=false.
    denied = session.execute(
        text(
            "SELECT ok FROM app.tool_call_log WHERE tool = 'query_metric' ORDER BY id DESC LIMIT 1"
        )
    ).scalar()
    assert denied is False


# ── 7. every call logged ──────────────────────────────────────────────────────


def test_every_call_in_tool_call_log(chat_session) -> None:
    """Each chat message's tool dispatch lands in tool_call_log, linked to the user message."""
    session, owner, _, _ = chat_session
    today = datetime.date.today()

    fake = ChatFakeLLMClient(
        intent={
            "intent": "question",
            "tool": "query_metric",
            "params": {
                "metric": "turnover",
                "from_date": str(today - datetime.timedelta(days=7)),
                "to_date": str(today),
            },
            "confidence": 0.9,
        }
    )

    conversation = _new_conversation(session, owner)
    before = session.execute(text("SELECT COUNT(*) FROM app.tool_call_log")).scalar()

    handle_message(session, owner, conversation, "Promet ove sedmice?", client=fake)
    handle_message(session, owner, conversation, "A prošle sedmice?", client=fake)

    rows = session.execute(
        text(
            "SELECT l.tool, l.ok, l.message_id, m.role FROM app.tool_call_log l "
            "JOIN app.message m ON m.id = l.message_id "
            "ORDER BY l.id DESC LIMIT 2"
        )
    ).all()
    after = session.execute(text("SELECT COUNT(*) FROM app.tool_call_log")).scalar()

    assert after == before + 2
    for row in rows:
        assert row.tool == "query_metric"
        assert row.ok is True
        assert row.message_id is not None
        assert row.role == "user"  # linked to the triggering user message


# ── 10/11/12. fallbacks, actions, stubs ───────────────────────────────────────


def test_intent_fallback_on_invalid_llm_output(chat_session) -> None:
    """Persistently malformed LLM output → a data-aware fallback, never an exception or raw output.

    Both the router AND the assistant narration fail here (the fake never produces valid
    JSON), so the deterministic fallback fires — and it still names real SQL counts instead
    of repeating one static line.
    """
    session, owner, _, _ = chat_session

    class BrokenFake:
        model = "fake-tier1"
        captured: list = []

        def complete(self, system: str, user: str) -> LLMResponse:
            return LLMResponse(
                text="ovo nikako nije json", model=self.model, tokens=10, latency_ms=5
            )

    # The real open-signal count the deterministic fallback must report.
    open_signals = session.execute(
        text("SELECT COUNT(*) FROM app.signal WHERE status IN ('new', 'tasked')")
    ).scalar()

    conversation = _new_conversation(session, owner)
    events = handle_message(session, owner, conversation, "asdfghjkl", client=BrokenFake())

    reply = _reply_text(events)
    assert _reply_register(events) == "analiza"
    assert "nije json" not in reply  # raw model output never reaches the user
    assert "Mogu odgovoriti" not in reply  # NOT the old canned line
    assert str(open_signals) in reply  # a real SQL count is surfaced
    assert "VALERI" in reply or "signal" in reply.lower()


def test_help_intent_uses_data_aware_assistant(chat_session) -> None:
    """A greeting (intent=help) → the LLM assistant reply grounded in the SQL bundle, not a tool."""
    session, owner, _, _ = chat_session

    fake = ChatFakeLLMClient(
        intent={"intent": "help", "tool": None, "params": {}, "confidence": 0.2}
    )

    conversation = _new_conversation(session, owner)
    events = handle_message(session, owner, conversation, "Zdravo VALERI", client=fake)

    # The reply is the narrated assistant answer (the fake echoes a valid ChatAnswer),
    # tagged analiza, with NO tool dispatched.
    assert _reply_register(events) == "analiza"
    assert _reply_text(events)
    assert not any(event.type == "tool_call" for event in events)
    done = next(event for event in events if event.type == "done")
    assert done.data["tool_calls"] == []

    # The assistant call was masked (no real customer name in any prompt).
    bundle_prompts = "\n".join(item["user"] for item in fake.captured)
    leaked = session.execute(
        text(
            "SELECT c.name FROM app.signal s JOIN core.customer c ON c.id = s.customer_id "
            "WHERE s.rule = 'customer_decline' AND s.status IN ('new', 'tasked') LIMIT 1"
        )
    ).scalar()
    if leaked:
        assert leaked not in bundle_prompts


def test_knowledge_question_routes_to_kb(chat_session) -> None:
    """'Šta znamo o <kupac>' → get_client_knowledge → captured KB content, not a fallback."""
    session, owner, _, _ = chat_session

    customer = session.execute(text("SELECT id, name FROM core.customer ORDER BY id LIMIT 1")).one()

    # Plant a confirmed KB fact so the tool has something to return.
    session.execute(
        text(
            "INSERT INTO app.client_fact "
            "(customer_id, fact_type, fact_key, value, source, confidence, conf_band, status, "
            " evidence_text) "
            "VALUES (:cid, 'preference', 'pakovanje', '{\"vrijednost\": \"veliko\"}', 'stated', "
            "0.9, 'visoka', 'active', 'Vole velika pakovanja.')"
        ),
        {"cid": customer.id},
    )
    session.flush()

    fake = ChatFakeLLMClient(
        intent={
            "intent": "question",
            "tool": "get_client_knowledge",
            "params": {"customer_ref": "{{KUPAC}}"},
            "confidence": 0.9,
        }
    )

    conversation = _new_conversation(session, owner)
    events = handle_message(
        session, owner, conversation, f"Šta znamo o kupcu {customer.name}?", client=fake
    )

    # Routed to the KB tool and logged.
    done = next(event for event in events if event.type == "done")
    assert done.data["tool_calls"][0]["tool"] == "get_client_knowledge"
    assert done.data["tool_calls"][0]["ok"] is True

    # No real customer name reached any prompt; the human reply is rehydrated.
    all_prompts = "\n".join(item["system"] + "\n" + item["user"] for item in fake.captured)
    assert customer.name not in all_prompts
    assert "Kupac-" in all_prompts
    assert _reply_register(events) == "analiza"


def test_knowledge_answer_renders_kb_content() -> None:
    """The deterministic KB rendering surfaces profile/facts/events/relationships."""
    output = {
        "customer_name": "Hotel Hills",
        "profile_summary": "Veliki hotel, redovne narudžbe.",
        "facts": [
            {"fact_type": "preference", "fact_key": "pakovanje", "value": "veliko",
             "conf_band": "visoka"}
        ],
        "events": [{"kind": "deal", "summary": "Godišnji ugovor", "value": "72000"}],
        "relationships": [{"rel_type": "same_owner", "other_name": "Hotel Europe"}],
    }
    rendered = _knowledge_answer(output)
    assert "Hotel Hills" in rendered
    assert "Veliki hotel" in rendered
    assert "pakovanje" in rendered
    assert "Godišnji ugovor" in rendered
    assert "Hotel Europe" in rendered


def test_knowledge_answer_handles_empty_kb() -> None:
    """An empty KB renders a friendly 'nothing yet' line, not an error."""
    rendered = _knowledge_answer(
        {"customer_name": "Kafić X", "profile_summary": None, "facts": [],
         "events": [], "relationships": []}
    )
    assert "Još nema zabilježenog znanja" in rendered
    assert "Kafić X" in rendered


def test_assistant_template_names_real_counts() -> None:
    """The deterministic fallback reports the real SQL counts, not a static line."""
    bundle = {
        "otvoreni_signali": 7,
        "otvoreni_zadaci": 3,
        "kupci_u_padu": [{"customer_id": 1, "customer_name": "Hotel Hills"}],
        "promet_30d": 142300,
    }
    rendered = _assistant_template(bundle)
    assert "7" in rendered and "3" in rendered
    assert "142300" in rendered
    assert "Hotel Hills" in rendered
    assert "Mogu odgovoriti" not in rendered  # not the retired static line


def test_kb_question_without_resolvable_customer_clarifies(chat_session) -> None:
    """A customer-scoped tool with no resolvable customer → a clarification, not a raw error."""
    session, owner, _, _ = chat_session

    fake = ChatFakeLLMClient(
        intent={
            "intent": "question",
            "tool": "get_client_knowledge",
            "params": {},  # the router couldn't bind a customer
            "confidence": 0.7,
        }
    )

    conversation = _new_conversation(session, owner)
    events = handle_message(session, owner, conversation, "šta znaš o tom kupcu?", client=fake)

    reply = _reply_text(events)
    assert "Neispravni parametri" not in reply  # never the raw validation error
    assert "kupca" in reply.lower()
    # Nothing was dispatched; the attempt is recorded as unresolved.
    assert not any(event.type == "tool_call" for event in events)
    done = next(event for event in events if event.type == "done")
    assert done.data["tool_calls"][0]["error_code"] == "unresolved_customer"


def test_unresolved_customer_reply_lists_candidates(chat_session) -> None:
    """When the message names a (possibly multi-object) customer, candidates are offered."""
    from valeri_api.conversation.service import _customer_candidates, _unresolved_customer_reply

    session, owner, _, _ = chat_session
    name = session.execute(text("SELECT name FROM core.customer ORDER BY id LIMIT 1")).scalar()

    candidates = _customer_candidates(session, owner, name)
    assert name in candidates

    reply = _unresolved_customer_reply(session, owner, name)
    assert name in reply
    assert "Nisam siguran" in reply


def test_rehydrate_handles_declined_pseudonym() -> None:
    """The model inflecting 'Kupac-x' → 'Kupca-x' must still rehydrate to the real name."""
    from valeri_api.llm.masking import MaskingContext, rehydrate

    context = MaskingContext()
    alias = context.register_customer(8, "Hotel Aria — recepcija i lobi")
    declined = alias.replace("Kupac", "Kupca")  # genitive, as the model often writes it

    out = rehydrate(f"Ukupan promet {declined} iznosi 100 KM.", context)
    assert "Hotel Aria — recepcija i lobi" in out
    assert "Kupac-" not in out and "Kupca-" not in out  # no pseudonym leaks


def test_followup_uses_customer_focus(chat_session) -> None:
    """A follow-up with no name reuses the customer just discussed instead of re-asking."""
    session, owner, _, _ = chat_session
    customer = session.execute(
        text(
            "SELECT c.id, c.name FROM core.customer c "
            "JOIN core.customer_metrics m ON m.customer_id = c.id "
            "WHERE m.turnover_60d > 0 ORDER BY c.id LIMIT 1"
        )
    ).one()

    conversation = _new_conversation(session, owner)
    # A prior turn established the customer in focus.
    session.add(
        Message(
            conversation_id=conversation.id,
            role="assistant",
            content=f"Podaci za kupca {customer.name}.",
        )
    )
    session.flush()

    fake = ChatFakeLLMClient(
        intent={"intent": "question", "tool": "get_customer_360", "params": {}, "confidence": 0.7}
    )
    events = handle_message(session, owner, conversation, "šta je sve kupio taj kupac?", client=fake)

    done = next(event for event in events if event.type == "done")
    assert done.data["tool_calls"][0]["tool"] == "get_customer_360"
    assert done.data["tool_calls"][0]["ok"] is True
    reply = _reply_text(events)
    assert "Nisam prepoznao" not in reply and "Nisam siguran" not in reply


def test_friendly_error_hides_raw_tool_error(chat_session) -> None:
    """A tool failure (missing period) becomes a clean Bosnian hint, not the raw error."""
    session, owner, _, _ = chat_session

    fake = ChatFakeLLMClient(
        intent={
            "intent": "question",
            "tool": "query_metric",
            "params": {"metric": "turnover"},  # no dates → the tool rejects it
            "confidence": 0.8,
        }
    )
    conversation = _new_conversation(session, owner)
    events = handle_message(session, owner, conversation, "izračunaj promet", client=fake)

    reply = _reply_text(events)
    assert "period" in reply.lower()
    assert "requires parameters" not in reply
    assert "Metric" not in reply  # no raw English / internal wording leaks


def test_action_intent_creates_task_draft(chat_session) -> None:
    """'Kreiraj zadatak za <kupac>' → task exists + akcija card + reversible decision."""
    session, owner, _, _ = chat_session
    customer = session.execute(text("SELECT id, name FROM core.customer ORDER BY id LIMIT 1")).one()

    fake = ChatFakeLLMClient(
        intent={
            "intent": "action",
            "tool": "create_task_draft",
            "params": {"customer_ref": "{{KUPAC}}", "title": "Nazvati kupca radi nove ponude"},
            "confidence": 0.9,
        }
    )

    conversation = _new_conversation(session, owner)
    events = handle_message(
        session,
        owner,
        conversation,
        f"Kreiraj zadatak za {customer.name}: nazvati ih radi nove ponude",
        client=fake,
    )

    # The task exists, assigned to the customer's rep.
    task = session.execute(
        text("SELECT id, title, register, status FROM app.task ORDER BY id DESC LIMIT 1")
    ).one()
    assert task.title == "Nazvati kupca radi nove ponude"
    assert task.register == "akcija"
    assert task.status == "open"

    # The inline card was streamed (akcija + status visible).
    card = next(event for event in events if event.type == "card")
    assert card.data["card_type"] == "task_draft"
    assert card.data["payload"]["task_id"] == task.id

    # The reversible decision exists (the /tool mutation contract).
    decision = session.execute(
        text("SELECT actor, reversible FROM app.decision ORDER BY id DESC LIMIT 1")
    ).one()
    assert decision.actor == "user"
    assert decision.reversible is True


def test_feedback_config_intent_proposes_real_rule(chat_session) -> None:
    """M10: the feedback_config intent runs the REAL propose_rule_change tool."""
    session, owner, _, _ = chat_session

    # The chat fake serves the intent prompt AND the proposer prompt.
    feedback_fake = ChatFakeLLMClient(
        intent={
            "intent": "feedback_config",
            "tool": None,
            "params": {"reason": "Svi kafići su sezonski, nemoj ih prijavljivati"},
            "confidence": 0.8,
        },
        proposal={
            "rule_type": "suppress",
            "scope": {"kind": "category", "rule": "customer_decline", "category": "kafić"},
            "description": "Ne prijavljuj pad prometa za kafiće — sezonska djelatnost.",
            "interpretation_confidence": 0.85,
        },
    )
    conversation = _new_conversation(session, owner)
    events = handle_message(
        session,
        owner,
        conversation,
        "Ne prijavljuj mi više sezonske kafiće",
        client=feedback_fake,
    )

    # A category proposal requires confirm → preporuka reply + a rule-proposal card.
    reply = _reply_text(events)
    assert "kafiće" in reply or "kafić" in reply
    assert "potvrda" in reply.lower()
    assert _reply_register(events) == "preporuka"

    card = next(event for event in events if event.type == "card")
    assert card.data["card_type"] == "rule_proposal"
    assert card.data["payload"]["requires_confirm"] is True

    # The pending rule is persisted; nothing is active, no decision yet.
    pending = session.execute(
        text("SELECT status FROM app.learned_rule ORDER BY id DESC LIMIT 1")
    ).scalar()
    assert pending == "pending_confirm"
    assert session.execute(text("SELECT COUNT(*) FROM app.decision")).scalar() == 0


def test_investigation_intent_creates_real_investigation(chat_session) -> None:
    """M13: the investigation intent runs the REAL start_investigation tool."""
    session, owner, _, _ = chat_session

    investigation_fake = ChatFakeLLMClient(
        intent={
            "intent": "investigation",
            "tool": None,
            "params": {"question": "Zašto pada promet u maju mjesecu?"},
            "confidence": 0.8,
        }
    )
    conversation = _new_conversation(session, owner)
    events = handle_message(
        session, owner, conversation, "Istraži zašto pada promet u maju", client=investigation_fake
    )

    # The reply confirms the investigation is running in the background.
    reply = _reply_text(events)
    assert "Istraga #" in reply
    assert "pozadini" in reply

    # The inline card links to it (the UI routes to AI Report → Istrage).
    card = next(event for event in events if event.type == "card")
    assert card.data["card_type"] == "investigation"
    investigation_id = card.data["payload"]["investigation_id"]

    # The investigation is queued in the DB (the worker will pick it up).
    status = session.execute(
        text("SELECT status FROM app.investigation WHERE id = :id"), {"id": investigation_id}
    ).scalar()
    assert status == "queued"


# ── 8/9. the API: SSE + session memory (monkeypatched gateway) ────────────────


@pytest.fixture
def fake_gateway(monkeypatch):
    """Patch the production client factory so API-level chat uses the fake."""
    today = datetime.date.today()
    fake = ChatFakeLLMClient(
        intent={
            "intent": "question",
            "tool": "query_metric",
            "params": {
                "metric": "turnover",
                "from_date": str(today - datetime.timedelta(days=30)),
                "to_date": str(today),
            },
            "confidence": 0.95,
        }
    )
    monkeypatch.setattr("valeri_api.llm.structured.get_llm_client", lambda: fake)
    return fake


@pytest.mark.anyio
async def test_sse_event_sequence(chat_db, fake_gateway) -> None:
    """The SSE stream yields tool_call → register → token → done, in order."""
    client = make_client()
    try:
        await login(client, OWNER_EMAIL)

        created = await client.post("/api/chat/sessions")
        assert created.status_code == 201
        session_id = created.json()["session_id"]

        response = await client.post(
            f"/api/chat/sessions/{session_id}/messages",
            json={"text": "Koliki je promet u zadnjih 30 dana?"},
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

        # Parse the SSE stream into typed events.
        events = [
            json.loads(line[len("data: ") :])
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        types = [event["type"] for event in events]
        assert types == ["tool_call", "register", "token", "done"]
        assert events[0]["tool"] == "query_metric"
        assert events[1]["register"] == "analiza"
        assert events[2]["text"]
        assert events[3]["message_id"]
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_session_memory_and_history(chat_db, fake_gateway, seed_data) -> None:
    """Sessions persist; history returns register + tool_calls; ownership is enforced."""
    owner_client = make_client()
    rep_client = make_client()
    try:
        await login(owner_client, OWNER_EMAIL)
        rep_user = next(user for user in seed_data.app_users if user["role"] == "sales_rep")
        await login(rep_client, rep_user["email"])

        # Owner creates a session and chats.
        created = await owner_client.post("/api/chat/sessions")
        session_id = created.json()["session_id"]
        await owner_client.post(
            f"/api/chat/sessions/{session_id}/messages", json={"text": "Koliki je promet?"}
        )

        # History: user + assistant messages, register + tool_calls present.
        history = await owner_client.get(f"/api/chat/sessions/{session_id}")
        assert history.status_code == 200
        body = history.json()
        assert body["title"] == "Koliki je promet?"
        roles = [message["role"] for message in body["messages"]]
        assert roles == ["user", "assistant"]
        assistant = body["messages"][1]
        assert assistant["register"] == "analiza"
        assert assistant["tool_calls"][0]["tool"] == "query_metric"

        # The session list shows the owner's session.
        listing = await owner_client.get("/api/chat/sessions")
        assert any(item["id"] == session_id for item in listing.json()["items"])

        # Another user cannot read it (403), and it's absent from their list.
        foreign = await rep_client.get(f"/api/chat/sessions/{session_id}")
        assert foreign.status_code == 403
        rep_listing = await rep_client.get("/api/chat/sessions")
        assert all(item["id"] != session_id for item in rep_listing.json()["items"])

        # Unauthenticated → 401.
        anonymous = make_client()
        try:
            denied = await anonymous.post("/api/chat/sessions")
            assert denied.status_code == 401
        finally:
            await anonymous.aclose()
    finally:
        await owner_client.aclose()
        await rep_client.aclose()
