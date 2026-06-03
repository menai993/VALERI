"""CSA Phase 2: the synchronous chat agent loop (act → collect → synthesize).

Uses the seeded tools DB (real invoices) and a fake LLM that scripts the act
steps and synthesizes a contract-safe answer (echoes a number from the payload).
"""

import datetime
import json

from valeri_api.conversation.agent import run_chat_agent
from valeri_api.llm.client import LLMResponse
from valeri_api.llm.masking import MaskingContext

_TODAY = datetime.date.today()
_FROM = _TODAY - datetime.timedelta(days=365)


class ChatAgentFake:
    """Routes by system prompt: scripted ToolChoice for act steps, echo-number synth."""

    def __init__(self, act_choices: list[dict]) -> None:
        self.act_choices = list(act_choices)
        self.model = "fake-tier1"
        self.captured: list[dict[str, str]] = []
        self.dispatched_acts = 0

    def complete(self, system: str, user: str) -> LLMResponse:
        self.captured.append({"system": system, "user": user})
        if "Biraš SLJEDEĆI alat" in system:  # ACT_SYSTEM_PROMPT
            self.dispatched_acts += 1
            choice = (
                self.act_choices.pop(0)
                if self.act_choices
                else {"tool": None, "params": {}, "reasoning": "imam dovoljno", "done": True}
            )
            return LLMResponse(text=json.dumps(choice), model=self.model, tokens=100, latency_ms=50)
        # synthesis: echo a number from the masked payload so the number contract holds.
        from valeri_api.llm.validators import extract_numbers

        payload = user[user.find("{") :]
        numbers = extract_numbers(payload)
        value = numbers[0] if numbers else "0"
        return LLMResponse(
            text=json.dumps(
                {"text": f"Na osnovu prikupljenih podataka, vrijednost iznosi {value}.",
                 "register": "analiza", "confidence": 0.9},
                ensure_ascii=False,
            ),
            model=self.model,
            tokens=100,
            latency_ms=50,
        )


def _metric_choice() -> dict:
    return {
        "tool": "query_metric",
        "params": {"metric": "turnover", "from_date": str(_FROM), "to_date": str(_TODAY)},
        "reasoning": "treba mi ukupan promet za period",
        "done": False,
    }


def test_loop_runs_tools_and_synthesizes(owner_context) -> None:
    """A multi-step question dispatches a read-only tool and synthesizes one answer."""
    fake = ChatAgentFake([_metric_choice()])  # one tool, then auto-done
    text, register, tool_calls, source = run_chat_agent(
        owner_context.session,
        owner_context.user,
        "uporedi promet kroz period i objasni",
        MaskingContext(),
        client=fake,
    )
    assert source == "llm"
    assert register == "analiza"
    assert text.strip()
    assert "Pouzdanost:" in text  # Principle 3: the synthesized conclusion carries a confidence band
    metric_calls = [c for c in tool_calls if c["tool"] == "query_metric"]
    assert metric_calls and metric_calls[0]["ok"] is True


def test_loop_respects_step_cap(owner_context) -> None:
    """A model that never says 'done' is bounded by chat_agent.max_steps (no infinite loop)."""
    from valeri_api.conversation.agent import _caps

    max_steps = _caps(owner_context.session)["max_steps"]
    fake = ChatAgentFake([_metric_choice() for _ in range(max_steps + 5)])
    _text, _register, tool_calls, source = run_chat_agent(
        owner_context.session,
        owner_context.user,
        "stalno traži još podataka",
        MaskingContext(),
        client=fake,
    )
    dispatched = [c for c in tool_calls if c["tool"] == "query_metric"]
    assert len(dispatched) == max_steps  # capped, then synthesized
    assert source in ("llm", "template")


def test_unknown_metric_not_dispatched(owner_context) -> None:
    """Honesty gate inside the loop: an unregistered metric is never dispatched."""
    bogus = {
        "tool": "query_metric",
        "params": {"metric": "izmisljena_metrika", "from_date": str(_FROM), "to_date": str(_TODAY)},
        "reasoning": "pokušaj s nepostojećom metrikom",
        "done": False,
    }
    fake = ChatAgentFake([bogus])
    _text, _register, tool_calls, _source = run_chat_agent(
        owner_context.session, owner_context.user, "nešto neodređeno", MaskingContext(), client=fake
    )
    assert any(c.get("error_code") == "unknown_metric" for c in tool_calls)
    assert not any(c.get("ok") for c in tool_calls)  # nothing bogus reached the DB
