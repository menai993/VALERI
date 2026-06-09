"""P2 chat-capture latency: the reply streams first; capture follows with a cap.

handle_message and _capture_event are monkeypatched at the api.chat seams — this
file tests the SSE generator's sequencing/timeout behaviour, not the KB pipeline
(covered in test_kb_*). Spec D7: on timeout the capture continues server-side,
only the inline chip is skipped.
"""

import json
import threading
import time

import pytest
from sqlalchemy import Engine

from tests.conftest import login, make_client
from valeri_api.conversation.models import Message
from valeri_api.conversation.schemas import SSEEvent
from valeri_api.seed.users import OWNER_EMAIL


def _fake_handle_message(session, user, conversation, text_in):
    """Persist the user/assistant rows (like the real pipeline) and return events."""
    session.add(Message(conversation_id=conversation.id, role="user", content=text_in))
    session.add(Message(conversation_id=conversation.id, role="assistant", content="odgovor"))
    return [
        SSEEvent(type="token", data={"text": "odgovor"}),
        SSEEvent(type="done", data={"tool_calls": []}),
    ]


def _sse_types(body: str) -> list[str]:
    return [
        json.loads(line[len("data: ") :])["type"]
        for line in body.splitlines()
        if line.startswith("data: ")
    ]


@pytest.mark.anyio
async def test_capture_chip_streams_before_done(seeded_db: Engine, monkeypatch) -> None:
    """A capture that finishes within the cap yields its chip right before 'done'."""
    import valeri_api.api.chat as chat_api

    monkeypatch.setenv("LLM_NARRATION_ENABLED", "true")
    monkeypatch.setattr(chat_api, "handle_message", _fake_handle_message)
    monkeypatch.setattr(
        chat_api,
        "_capture_event",
        lambda message_id, user_id, text_in: SSEEvent(
            type="capture",
            data={"auto_saved": 1, "proposed": 0, "clarifications": 0, "titles": ["x"]},
        ),
    )

    client = make_client()
    try:
        await login(client, OWNER_EMAIL)
        session_id = (await client.post("/api/chat/sessions")).json()["session_id"]
        response = await client.post(
            f"/api/chat/sessions/{session_id}/messages", json={"text": "zabilješka"}
        )
        assert response.status_code == 200
        assert _sse_types(response.text) == ["token", "capture", "done"]
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_slow_capture_never_blocks_the_stream(seeded_db: Engine, monkeypatch) -> None:
    """Capture slower than the cap: stream closes without the chip; capture finishes."""
    import valeri_api.api.chat as chat_api

    monkeypatch.setenv("LLM_NARRATION_ENABLED", "true")
    monkeypatch.setenv("CHAT_CAPTURE_TIMEOUT_SECONDS", "0.2")
    monkeypatch.setattr(chat_api, "handle_message", _fake_handle_message)

    finished = threading.Event()

    def slow_capture(message_id, user_id, text_in):
        time.sleep(1.0)
        finished.set()
        return SSEEvent(type="capture", data={"auto_saved": 1})

    monkeypatch.setattr(chat_api, "_capture_event", slow_capture)

    client = make_client()
    try:
        await login(client, OWNER_EMAIL)
        session_id = (await client.post("/api/chat/sessions")).json()["session_id"]
        started = time.monotonic()
        response = await client.post(
            f"/api/chat/sessions/{session_id}/messages", json={"text": "spora zabilješka"}
        )
        elapsed = time.monotonic() - started

        assert response.status_code == 200
        types = _sse_types(response.text)
        assert "capture" not in types  # chip skipped…
        assert types[-1] == "done"  # …but the reply completed
        assert elapsed < 0.9  # the 1s capture did not block the stream
        assert finished.wait(timeout=3.0)  # capture continued server-side
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_no_capture_when_narration_disabled(seeded_db: Engine, monkeypatch) -> None:
    """With narration off (test/default posture) capture never runs."""
    import valeri_api.api.chat as chat_api

    monkeypatch.setattr(chat_api, "handle_message", _fake_handle_message)

    def must_not_run(message_id, user_id, text_in):  # pragma: no cover
        raise AssertionError("capture must not run when narration is disabled")

    monkeypatch.setattr(chat_api, "_capture_event", must_not_run)

    client = make_client()
    try:
        await login(client, OWNER_EMAIL)
        session_id = (await client.post("/api/chat/sessions")).json()["session_id"]
        response = await client.post(
            f"/api/chat/sessions/{session_id}/messages", json={"text": "zdravo"}
        )
        assert _sse_types(response.text) == ["token", "done"]
    finally:
        await client.aclose()
