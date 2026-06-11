"""P3 answer cache: identical masked simple_qa answers inside the TTL skip the API.

A hit makes no LLM call and writes no ai_log row. The key is built post-masking
(role + masked system + masked user), and only whitelisted roles are cached.
"""

import json

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.llm.answer_cache import answer_cache
from valeri_api.llm.client import LLMResponse
from valeri_api.llm.router.roles import ROLE_KB_SUMMARY, ROLE_SIMPLE_QA
from valeri_api.llm.structured import narrate_structured

pytestmark = pytest.mark.usefixtures("db_engine")


class _CountingFake:
    model = "claude-haiku-4-5"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, system: str, user: str) -> LLMResponse:
        self.calls += 1
        return LLMResponse(
            text=json.dumps({"text": "Odgovor iz baze.", "register": "analiza"}),
            model=self.model,
            tokens=100,
            latency_ms=10,
            input_tokens=80,
            output_tokens=20,
        )


def _schema():
    from pydantic import BaseModel

    class _Out(BaseModel):
        text: str
        register: str

    return _Out


@pytest.fixture(autouse=True)
def _clear_cache(monkeypatch):
    # Caching is off by default in tests (conftest); enable it for this module.
    monkeypatch.setenv("LLM_ANSWER_CACHE_TTL_SECONDS", "300")
    from valeri_api.config import get_settings

    get_settings.cache_clear()
    answer_cache.reset()
    yield
    answer_cache.reset()


def _ailog_count(session: Session) -> int:
    return session.execute(text("SELECT count(*) FROM audit.ai_log")).scalar_one()


def test_hit_skips_client_and_logs_nothing(db_session: Session) -> None:
    fake = _CountingFake()
    schema = _schema()
    before = _ailog_count(db_session)

    args = dict(
        masked_payload={"q": "prihod"},
        schema=schema,
        system_prompt="sys",
        instruction="odgovori",
        client=fake,
        role=ROLE_SIMPLE_QA,
    )
    narrate_structured(db_session, **args)
    db_session.flush()
    after_first = _ailog_count(db_session)
    assert fake.calls == 1
    assert after_first == before + 1  # the first call logged

    # Identical masked question → cache hit: no client call, no new ai_log row.
    out, model, attempts = narrate_structured(db_session, **args)
    db_session.flush()
    assert fake.calls == 1  # client NOT called again
    assert attempts == 0  # 0 attempts signals a cache hit
    assert _ailog_count(db_session) == after_first
    assert out.text == "Odgovor iz baze."


def test_non_whitelisted_role_not_cached(db_session: Session) -> None:
    fake = _CountingFake()
    schema = _schema()
    args = dict(
        masked_payload={"q": "prihod"},
        schema=schema,
        system_prompt="sys",
        instruction="odgovori",
        client=fake,
        role=ROLE_KB_SUMMARY,  # not in CACHEABLE_ROLES
        text_field=None,
    )
    narrate_structured(db_session, **args)
    narrate_structured(db_session, **args)
    assert fake.calls == 2  # no caching → the client answered both


def test_post_masking_key_differs_by_payload(db_session: Session) -> None:
    fake = _CountingFake()
    schema = _schema()
    base = dict(
        schema=schema,
        system_prompt="sys",
        instruction="odgovori",
        client=fake,
        role=ROLE_SIMPLE_QA,
    )
    narrate_structured(db_session, masked_payload={"q": "prihod maj"}, **base)
    narrate_structured(db_session, masked_payload={"q": "prihod juni"}, **base)
    assert fake.calls == 2  # different masked payloads → different keys, no hit


def test_ttl_expiry(db_session: Session, monkeypatch) -> None:
    monkeypatch.setenv("LLM_ANSWER_CACHE_TTL_SECONDS", "0")  # nothing is retained
    from valeri_api.config import get_settings

    get_settings.cache_clear()
    fake = _CountingFake()
    schema = _schema()
    args = dict(
        masked_payload={"q": "prihod"},
        schema=schema,
        system_prompt="sys",
        instruction="odgovori",
        client=fake,
        role=ROLE_SIMPLE_QA,
    )
    narrate_structured(db_session, **args)
    narrate_structured(db_session, **args)
    assert fake.calls == 2  # TTL 0 → never cached
