"""Shared LLM test doubles (M7+). No real API calls ever happen in tests."""

import json
import re

from valeri_api.llm.client import LLMResponse

_PSEUDONYM = re.compile(r"Kupac-[0-9a-f]{6}")


class AutoFakeLLMClient:
    """A rule-following fake: returns a valid narrative for every prompt.

    Mimics an LLM that obeys the system prompt — it echoes only numbers that
    appear in the prompt's masked payload (so the number contract holds) and
    uses the pseudonyms it finds there (so masking/rehydration is exercised).
    Captures every (system, user) prompt pair for PII assertions.
    """

    def __init__(self) -> None:
        self.captured: list[dict[str, str]] = []
        self.model = "fake-tier1"

    def complete(self, system: str, user: str) -> LLMResponse:
        from valeri_api.llm.validators import extract_numbers

        self.captured.append({"system": system, "user": user})

        # Echo only from the payload part (the JSON block), never the instructions.
        start = user.find("{")
        payload_text = user[start:] if start >= 0 else ""
        numbers = extract_numbers(payload_text)
        pseudonyms = _PSEUDONYM.findall(payload_text)

        parts = ["Pregled poslovanja pokazuje sljedeće stanje iz baze podataka."]
        if pseudonyms:
            parts.append(f"Kupac {pseudonyms[0]} zahtijeva posebnu pažnju komercijaliste.")
        if numbers:
            parts.append(f"Ključna vrijednost iznosi {numbers[0]}.")
        parts.append("Preporučuje se pregled navedenih stavki.")

        return LLMResponse(
            text=json.dumps({"text": " ".join(parts), "register": "analiza"}, ensure_ascii=False),
            model=self.model,
            tokens=100,
            latency_ms=50,
        )


class ScriptedFakeLLMClient:
    """Returns scripted responses in order; raises queued exceptions."""

    def __init__(self, responses: list[str | Exception]) -> None:
        self.responses = list(responses)
        self.captured: list[dict[str, str]] = []
        self.model = "fake-tier1"

    def complete(self, system: str, user: str) -> LLMResponse:
        self.captured.append({"system": system, "user": user})
        if not self.responses:
            raise AssertionError("ScriptedFakeLLMClient ran out of scripted responses")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return LLMResponse(text=item, model=self.model, tokens=100, latency_ms=50)
