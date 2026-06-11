"""P3 Batch API client + live fallback for non-interactive jobs (the weekly cycle).

The Anthropic Batch API runs non-real-time work at ~half price. The weekly owner
report, bulk task bodies, and the over-suppression audit aren't latency-sensitive,
so they go through here; live calls stay reserved for chat and on-demand actions.

LiteLLMBatchClient submits a one-item batch and polls (the 50% rate applies
regardless of batch size, so we avoid refactoring the report builder into a bulk
submitter). Any failure or timeout raises LLMUnavailable; FallbackClient turns
that into a live call so a batch hiccup never loses the weekly report.
"""

import logging
import time

from valeri_api.config import get_settings
from valeri_api.llm.client import LiteLLMClient, LLMClient, LLMResponse, LLMUnavailable

logger = logging.getLogger("valeri.llm.batch")


class LiteLLMBatchClient:
    """An LLMClient that answers via the gateway's Batch API (batched=True, ~half price).

    Implements the same `complete(system, user)` protocol as LiteLLMClient, so it
    drops into narrate_* via the `client=` seam. Marks its responses batched so the
    cost ledger applies the batch discount.
    """

    def __init__(self, model: str | None = None) -> None:
        settings = get_settings()
        self.model = model or settings.llm_tier1_alias
        self._poll = settings.llm_batch_poll_seconds
        self._timeout = settings.llm_batch_timeout_seconds

    def complete(self, system: str, user: str) -> LLMResponse:  # pragma: no cover — needs gateway
        from openai import OpenAI, OpenAIError

        settings = get_settings()
        client = OpenAI(
            base_url=settings.litellm_base_url, api_key=settings.litellm_master_key or "unused"
        )
        started = time.monotonic()
        try:
            batch = client.batches.create(
                completion_window="24h",
                endpoint="/v1/chat/completions",
                input_file_id=self._upload(client, system, user),
            )
            output = self._await_result(client, batch.id, started)
        except OpenAIError as error:
            raise LLMUnavailable(f"batch call failed: {error}") from error

        usage = output.get("usage", {})
        return LLMResponse(
            text=output["text"],
            model=output.get("model", self.model),
            tokens=usage.get("total_tokens"),
            latency_ms=int((time.monotonic() - started) * 1000),
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            batched=True,
        )

    def _upload(self, client, system: str, user: str) -> str:  # pragma: no cover — needs gateway
        import io
        import json

        line = {
            "custom_id": "weekly-1",
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        }
        buffer = io.BytesIO(json.dumps(line).encode())
        uploaded = client.files.create(file=buffer, purpose="batch")
        return uploaded.id

    def _await_result(self, client, batch_id: str, started: float) -> dict:  # pragma: no cover
        import json

        while True:
            batch = client.batches.retrieve(batch_id)
            if batch.status in {"completed", "ended"}:
                break
            if batch.status in {"failed", "cancelled", "expired"}:
                raise LLMUnavailable(f"batch {batch_id} ended with status {batch.status}")
            if time.monotonic() - started > self._timeout:
                raise LLMUnavailable(f"batch {batch_id} timed out after {self._timeout}s")
            time.sleep(self._poll)

        content = client.files.content(batch.output_file_id)
        result = json.loads(content.read().decode().splitlines()[0])
        body = result["response"]["body"]
        return {
            "text": body["choices"][0]["message"]["content"] or "",
            "model": body.get("model", self.model),
            "usage": body.get("usage", {}),
        }


class FallbackClient:
    """Try `primary`; on LLMUnavailable, answer with `fallback` (live).

    Used to wrap the batch client so a batch failure/timeout degrades to a live
    call — the weekly report completes either way.
    """

    def __init__(self, primary: LLMClient, fallback: LLMClient) -> None:
        self._primary = primary
        self._fallback = fallback
        self.model = getattr(primary, "model", getattr(fallback, "model", "unknown"))

    def complete(self, system: str, user: str) -> LLMResponse:
        try:
            return self._primary.complete(system, user)
        except LLMUnavailable as error:
            logger.warning("batch path unavailable (%s) — falling back to a live call", error)
            return self._fallback.complete(system, user)


def weekly_batch_client(tier_alias: str | None = None) -> LLMClient | None:
    """The client the weekly cycle narrates through: batch → live fallback.

    None when batching is disabled (the caller then uses the default live path).
    """
    settings = get_settings()
    if not settings.llm_batch_enabled:
        return None
    alias = tier_alias or settings.llm_tier1_alias
    return FallbackClient(LiteLLMBatchClient(model=alias), LiteLLMClient(model=alias))
