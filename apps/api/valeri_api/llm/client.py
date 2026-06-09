"""OpenAI-compatible client to the LiteLLM gateway (hosted Claude tiers).

The client is a small, injectable boundary: production uses LiteLLMClient
(openai SDK → gateway); tests inject a fake. Nothing else in the codebase
talks to the network.
"""

import time
from typing import Protocol

from pydantic import BaseModel

from valeri_api.config import get_settings


class LLMResponse(BaseModel):
    """What one LLM call returned (transport-level, before any validation)."""

    text: str
    model: str
    tokens: int | None = None
    latency_ms: int | None = None


class LLMClient(Protocol):
    """Anything that can answer a (system, user) prompt pair."""

    def complete(self, system: str, user: str) -> LLMResponse: ...


class LLMUnavailable(Exception):
    """The gateway could not be reached or returned a transport-level error."""


class LiteLLMClient:
    """The production client: OpenAI-compatible chat completions via LiteLLM.

    The model name is a LiteLLM alias ("tier1"/"tier2"/"tier2_strong" → the Claude
    models in infra/litellm.config.yaml); swapping the underlying model is
    config-only. Stable system prompts are marked cacheable (M12 cost lever) —
    LiteLLM forwards the Anthropic cache_control block.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        settings = get_settings()
        self._base_url = base_url or settings.litellm_base_url
        self._api_key = api_key or settings.litellm_master_key
        self.model = model or settings.llm_tier1_alias

    def _build_messages(self, system: str, user: str, cache_system: bool) -> list[dict]:
        """The chat payload; with caching, the system prompt carries cache_control.

        Anthropic caches prompt prefixes above its minimum token count and silently
        ignores the marker below it — marking is always safe.
        """
        if cache_system:
            system_message = {
                "role": "system",
                "content": [
                    {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
                ],
            }
        else:
            system_message = {"role": "system", "content": system}
        return [system_message, {"role": "user", "content": user}]

    def complete(self, system: str, user: str) -> LLMResponse:
        from openai import OpenAI, OpenAIError

        settings = get_settings()
        client = OpenAI(base_url=self._base_url, api_key=self._api_key or "unused", timeout=60)
        started = time.monotonic()
        # Claude Opus 4.8 (the strong tier) rejects the deprecated `temperature`
        # param with a 400; the cheaper tiers still accept it and benefit from
        # low-variance sampling. Send it only where it is supported.
        create_kwargs: dict = {
            "model": self.model,
            "messages": self._build_messages(
                system, user, cache_system=settings.llm_prompt_cache_enabled
            ),
        }
        if self.model != settings.llm_tier2_strong_alias:
            create_kwargs["temperature"] = 0.2
        try:
            response = client.chat.completions.create(**create_kwargs)
        except OpenAIError as error:
            raise LLMUnavailable(str(error)) from error

        latency_ms = int((time.monotonic() - started) * 1000)
        usage = getattr(response, "usage", None)
        return LLMResponse(
            text=response.choices[0].message.content or "",
            model=response.model or self.model,
            tokens=getattr(usage, "total_tokens", None),
            latency_ms=latency_ms,
        )


def get_llm_client(tier: str = "tier1") -> LiteLLMClient:
    """A production client for one tier (default: Tier-1).

    Kept for backward compatibility and non-routed utility use; routed code paths
    go through llm.router (which picks the tier from the task role).
    """
    settings = get_settings()
    tier_models = {
        "tier1": settings.llm_tier1_alias,
        "tier2": settings.llm_tier2_alias,
        "tier2_strong": settings.llm_tier2_strong_alias,
    }
    return LiteLLMClient(model=tier_models.get(tier, settings.llm_tier1_alias))
