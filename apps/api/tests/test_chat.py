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
from valeri_api.conversation.models import Conversation
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

    def __init__(self, intent: dict) -> None:
        self.intent_json = json.dumps(intent, ensure_ascii=False)
        self.captured: list[dict[str, str]] = []
        self.model = "fake-tier1"

    def complete(self, system: str, user: str) -> LLMResponse:
        self.captured.append({"system": system, "user": user})
        if "usmjerivač namjera" in system:
            text_out = self.intent_json
            pseudonym = re.search(r"Kupac-[0-9a-f]{6}", user)
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
    """Persistently malformed router output → help reply, never an exception or raw output."""
    session, owner, _, _ = chat_session

    class BrokenFake:
        model = "fake-tier1"
        captured: list = []

        def complete(self, system: str, user: str) -> LLMResponse:
            return LLMResponse(
                text="ovo nikako nije json", model=self.model, tokens=10, latency_ms=5
            )

    conversation = _new_conversation(session, owner)
    events = handle_message(session, owner, conversation, "asdfghjkl", client=BrokenFake())

    reply = _reply_text(events)
    assert "Mogu odgovoriti" in reply  # the help text
    assert _reply_register(events) == "analiza"
    assert "nije json" not in reply  # raw model output never reaches the user


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


def test_stub_intents_reply_milestone_note(chat_session) -> None:
    """feedback_config / investigation intents reply honestly with the milestone note."""
    session, owner, _, _ = chat_session

    # feedback_config → propose_rule_change stub (the intent's default tool).
    feedback_fake = ChatFakeLLMClient(
        intent={
            "intent": "feedback_config",
            "tool": None,
            "params": {"reason": "Sezonski kupac"},
            "confidence": 0.8,
        }
    )
    conversation = _new_conversation(session, owner)
    events = handle_message(
        session, owner, conversation, "Ne prijavljuj mi više sezonske kafiće", client=feedback_fake
    )
    assert "M10" in _reply_text(events)

    # investigation → start_investigation stub.
    investigation_fake = ChatFakeLLMClient(
        intent={
            "intent": "investigation",
            "tool": None,
            "params": {"question": "Zašto pada promet?"},
            "confidence": 0.8,
        }
    )
    events = handle_message(
        session, owner, conversation, "Istraži zašto pada promet u maju", client=investigation_fake
    )
    assert "M13" in _reply_text(events)


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
