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

    The model name is a LiteLLM alias ("tier1" → Claude Haiku 4.5 per
    infra/litellm.config.yaml); swapping the underlying model is config-only.
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
        self.model = model or settings.llm_tier1_model

    def complete(self, system: str, user: str) -> LLMResponse:
        from openai import OpenAI, OpenAIError

        client = OpenAI(base_url=self._base_url, api_key=self._api_key or "unused", timeout=60)
        started = time.monotonic()
        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.2,
            )
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


def get_llm_client() -> LiteLLMClient:
    """The default production client (Tier-1 narration model)."""
    return LiteLLMClient()
