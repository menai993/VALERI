"""P3 answer cache: a short-TTL in-process cache for identical masked questions.

Caches whole LLM answers (not just prompt prefixes) for whitelisted roles so a
repeated "prihod ovog mjeseca" inside the TTL window answers without an API call
(and writes no ai_log row). The key is built POST-masking — it can never depend
on raw PII (principle 6 holds: masking runs before the key is computed).
"""

import hashlib
import time

from valeri_api.config import get_settings
from valeri_api.llm.client import LLMResponse
from valeri_api.llm.router.roles import ROLE_SIMPLE_QA

# Only deterministic, high-repeat roles are cached. Chat Q&A over tool output is
# the canonical case; narration/extraction vary per signal and are NOT cached.
CACHEABLE_ROLES = frozenset({ROLE_SIMPLE_QA})


class _AnswerCache:
    """Minute-scale TTL cache keyed by sha256(role + system + user) — all masked."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[float, LLMResponse]] = {}

    @staticmethod
    def key(role: str, system: str, user: str) -> str:
        digest = hashlib.sha256(f"{role}\x00{system}\x00{user}".encode()).hexdigest()
        return digest

    def get(self, role: str, system: str, user: str) -> LLMResponse | None:
        if role not in CACHEABLE_ROLES:
            return None
        entry = self._store.get(self.key(role, system, user))
        if entry is None:
            return None
        expires_at, response = entry
        if time.monotonic() >= expires_at:
            self._store.pop(self.key(role, system, user), None)
            return None
        return response

    def put(self, role: str, system: str, user: str, response: LLMResponse) -> None:
        if role not in CACHEABLE_ROLES:
            return
        ttl = get_settings().llm_answer_cache_ttl_seconds
        if ttl <= 0:
            return
        self._store[self.key(role, system, user)] = (time.monotonic() + ttl, response)

    def reset(self) -> None:
        self._store.clear()


answer_cache = _AnswerCache()
