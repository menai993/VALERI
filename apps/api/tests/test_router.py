"""M12 acceptance: the tiered LLM router (TDD — written before the implementation).

1. Each role maps to its configured tier; the mapping lives in app.rule_config.
2. Cascade escalates on low self-confidence and on validator-reject (capped, config-gated).
3. Every routing decision lands in audit.llm_route_log (append-only).
4. Swapping a tier's model (Sonnet↔Opus) is config-only and PII masking holds on every tier.

All LLM interaction uses fakes — no gateway needed.
"""

import inspect
import json
from typing import Literal

import pytest
from pydantic import BaseModel, Field
from sqlalchemy import text

from tests.fakes import AutoFakeLLMClient, ScriptedFakeLLMClient
from valeri_api.config import get_settings
from valeri_api.llm.client import LiteLLMClient
from valeri_api.llm.schemas import NarrationFailed
from valeri_api.llm.structured import narrate_structured

# ── a minimal output schema with a confidence field (drives cascade) ──────────


class _RoutedOutput(BaseModel):
    text: str = Field(min_length=5)
    register: Literal["analiza", "preporuka", "akcija"] = "analiza"
    confidence: float = Field(ge=0, le=1, default=0.9)


def _response(text_value: str, confidence: float) -> str:
    return json.dumps(
        {"text": text_value, "register": "analiza", "confidence": confidence},
        ensure_ascii=False,
    )


GOOD = _response("Siguran odgovor iz baze podataka.", 0.9)
LOW_CONFIDENCE = _response("Nesiguran odgovor, treba provjera.", 0.3)
ESCALATED_GOOD = _response("Pouzdan odgovor nakon eskalacije.", 0.95)
INVALID = "ovo nije validan JSON odgovor"

SYSTEM = "Testni sistemski prompt za ruter."
INSTRUCTION = "Odgovori na testni upit."


@pytest.fixture
def db_session(db_session):
    """The conftest db_session with a clean route log.

    Other test files commit route-log rows (chat/report/selfconfig API tests run
    through the routed path); this TRUNCATE happens inside the rolled-back
    transaction, so the audit rows of other tests survive the run untouched.
    """
    db_session.execute(text("TRUNCATE audit.llm_route_log"))
    return db_session


def _routes(session) -> list:
    return session.execute(
        text(
            "SELECT request_id, task_role, chosen_tier, model, reason, confidence "
            "FROM audit.llm_route_log ORDER BY id"
        )
    ).all()


def _narrate(session, client, role=None, payload=None):
    kwargs = {"client": client}
    if role is not None:
        kwargs["role"] = role
    return narrate_structured(
        session,
        payload or {"podaci": "testna vrijednost"},
        _RoutedOutput,
        system_prompt=SYSTEM,
        instruction=INSTRUCTION,
        **kwargs,
    )


# ── 1. role → tier mapping (acceptance 1) ─────────────────────────────────────


def test_each_role_maps_to_configured_tier(db_session) -> None:
    """Every default role routes to its tier; the production client carries the right alias."""
    from valeri_api.llm.router.router import client_for, initial_route

    expectations = {
        "narration": "tier1",
        "intent": "tier1",
        "simple_qa": "tier1",
        "nl_rule": "tier1",
        "report_narration": "tier1",
        "customer_draft": "tier1",
        "over_suppression_audit": "tier2",
        "investigation": "tier2",
        "investigation_synthesis": "tier2_strong",
    }
    for role, expected_tier in expectations.items():
        decision = initial_route(db_session, role)
        assert decision.chosen_tier == expected_tier, role
        client = client_for(decision)
        assert isinstance(client, LiteLLMClient)
        assert client.model == expected_tier  # the LiteLLM alias IS the tier name


def test_unknown_role_defaults_to_tier1(db_session) -> None:
    """An unregistered role falls back to the cheapest tier (fail-cheap, never fail-expensive)."""
    from valeri_api.llm.router.router import initial_route

    decision = initial_route(db_session, "some_future_role")
    assert decision.chosen_tier == "tier1"


def test_role_tiers_live_in_rule_config(db_session) -> None:
    """Flipping a role's tier in the DB changes routing — nothing is hard-coded."""
    from valeri_api.llm.router.router import initial_route, load_router_config

    config = load_router_config(db_session)
    role_tiers = dict(config["role_tiers"])
    role_tiers["over_suppression_audit"] = "tier1"
    db_session.execute(
        text(
            "UPDATE app.rule_config SET value = CAST(:value AS jsonb) "
            "WHERE rule = 'llm_router' AND param = 'role_tiers'"
        ),
        {"value": json.dumps(role_tiers)},
    )

    decision = initial_route(db_session, "over_suppression_audit")
    assert decision.chosen_tier == "tier1"


def test_haiku_share_by_construction(db_session) -> None:
    """All interactive + scan-volume roles default to tier1 (the 60-70% Haiku target)."""
    from valeri_api.llm.router.router import load_router_config

    config = load_router_config(db_session)
    high_volume_roles = {
        "narration",
        "intent",
        "simple_qa",
        "nl_rule",
        "report_narration",
        "customer_draft",
    }
    tier1_roles = {role for role, tier in config["role_tiers"].items() if tier == "tier1"}
    assert high_volume_roles.issubset(tier1_roles)


# ── 2. cascade escalation (acceptance 2) ──────────────────────────────────────


def test_cascade_escalates_on_low_confidence(db_session) -> None:
    """A valid but low-confidence output triggers ONE escalation; the higher tier's result wins."""
    fake = ScriptedFakeLLMClient([LOW_CONFIDENCE, ESCALATED_GOOD])

    result, _, _ = _narrate(db_session, fake, role="simple_qa")

    # The escalated (second) response is the one returned.
    assert result.confidence == 0.95
    assert "eskalacije" in result.text
    assert len(fake.captured) == 2

    # Both routing decisions are logged: initial + the escalation with its trigger.
    routes = _routes(db_session)
    assert len(routes) == 2
    assert routes[0].task_role == "simple_qa"
    assert routes[0].chosen_tier == "tier1"
    assert routes[0].reason == "injected_client"
    assert routes[1].chosen_tier == "tier2"
    assert routes[1].reason == "low_confidence"
    assert float(routes[1].confidence) == pytest.approx(0.3)  # what triggered it
    # One logical request → one request_id across both entries.
    assert routes[0].request_id == routes[1].request_id


def test_cascade_escalates_on_validator_reject(db_session) -> None:
    """Output that keeps failing validation on tier1 escalates; tier2's output is accepted."""
    max_attempts = get_settings().llm_max_retries + 1
    fake = ScriptedFakeLLMClient([INVALID] * max_attempts + [ESCALATED_GOOD])

    result, _, _ = _narrate(db_session, fake, role="narration")

    assert "eskalacije" in result.text
    routes = _routes(db_session)
    assert [route.reason for route in routes] == ["injected_client", "validator_reject"]
    assert [route.chosen_tier for route in routes] == ["tier1", "tier2"]


def test_cascade_caps_at_one_escalation(db_session) -> None:
    """Everything failing on both tiers → NarrationFailed; never a third tier."""
    max_attempts = get_settings().llm_max_retries + 1
    fake = ScriptedFakeLLMClient([INVALID] * (max_attempts * 3))

    with pytest.raises(NarrationFailed):
        _narrate(db_session, fake, role="narration")

    routes = _routes(db_session)
    assert len(routes) == 2  # initial + exactly ONE escalation
    # The budget: full retries on each of the two tiers, nothing more.
    assert len(fake.captured) == 2 * max_attempts


def test_low_confidence_fallback_when_escalation_fails(db_session) -> None:
    """If the escalated tier produces garbage, the valid low-confidence original is used."""
    max_attempts = get_settings().llm_max_retries + 1
    fake = ScriptedFakeLLMClient([LOW_CONFIDENCE] + [INVALID] * max_attempts)

    result, _, _ = _narrate(db_session, fake, role="simple_qa")

    # The tier-1 result (valid, just unsure) is better than nothing.
    assert result.confidence == 0.3
    assert "Nesiguran" in result.text


def test_cascade_disabled_in_config(db_session) -> None:
    """cascade_enabled=false → low confidence is used as-is, exactly one call, one route."""
    db_session.execute(
        text(
            "UPDATE app.rule_config SET value = CAST('false' AS jsonb) "
            "WHERE rule = 'llm_router' AND param = 'cascade_enabled'"
        )
    )
    fake = ScriptedFakeLLMClient([LOW_CONFIDENCE])

    result, _, _ = _narrate(db_session, fake, role="simple_qa")

    assert result.confidence == 0.3
    assert len(fake.captured) == 1
    routes = _routes(db_session)
    assert len(routes) == 1


def test_tier2_role_escalates_to_tier2_strong(db_session) -> None:
    """A tier2 role's escalation goes to tier2_strong (the Sonnet→Opus cascade)."""
    fake = ScriptedFakeLLMClient([LOW_CONFIDENCE, ESCALATED_GOOD])

    _narrate(db_session, fake, role="over_suppression_audit")

    routes = _routes(db_session)
    assert [route.chosen_tier for route in routes] == ["tier2", "tier2_strong"]


# ── 3. every route logged, append-only (acceptance 3) ─────────────────────────


def test_every_route_logged(db_session) -> None:
    """narrate_structured AND narrate_task each log a complete route row per call."""
    from valeri_api.llm.narration import narrate_task

    # structured path
    _narrate(db_session, ScriptedFakeLLMClient([GOOD]), role="simple_qa")

    # task-narration path (M6) — TaskNarration schema: body/register/confidence
    task_fake = ScriptedFakeLLMClient(
        [
            json.dumps(
                {
                    "body": "Kupac je smanjio narudžbe — kontaktirati ga ove sedmice.",
                    "register": "preporuka",
                    "confidence": 0.9,
                },
                ensure_ascii=False,
            )
        ]
    )
    narrate_task(
        db_session,
        rule="customer_decline",
        evidence={"metric": "turnover_60d", "value": "100.00"},
        customer_id=None,
        customer_name=None,
        segment="hotel",
        client=task_fake,
    )

    routes = _routes(db_session)
    assert len(routes) == 2
    for route in routes:
        assert route.request_id
        assert route.task_role in ("simple_qa", "narration")
        assert route.chosen_tier
        assert route.model
        assert route.reason


def test_default_role_when_not_specified(db_session) -> None:
    """Callers that don't pass a role get 'narration' (backward compatible)."""
    _narrate(db_session, ScriptedFakeLLMClient([GOOD]))  # no role kwarg

    routes = _routes(db_session)
    assert len(routes) == 1
    assert routes[0].task_role == "narration"


def test_route_log_writer_is_append_only() -> None:
    """The route-log writer has no update/delete path (like every audit writer)."""
    from valeri_api.audit import route_log

    source = inspect.getsource(route_log).lower()
    assert "update" not in source
    assert "delete" not in source


# ── 4. config-only tier swap + masking holds (acceptance 4) ──────────────────


def test_tier_swap_is_config_only(db_session) -> None:
    """Pointing the audit role at tier2_strong (Sonnet→Opus) is a pure config change."""
    from valeri_api.llm.router.router import client_for, initial_route, load_router_config

    config = load_router_config(db_session)
    role_tiers = dict(config["role_tiers"])
    role_tiers["over_suppression_audit"] = "tier2_strong"
    db_session.execute(
        text(
            "UPDATE app.rule_config SET value = CAST(:value AS jsonb) "
            "WHERE rule = 'llm_router' AND param = 'role_tiers'"
        ),
        {"value": json.dumps(role_tiers)},
    )

    decision = initial_route(db_session, "over_suppression_audit")
    assert decision.chosen_tier == "tier2_strong"
    assert client_for(decision).model == "tier2_strong"


def test_masking_unaffected_by_routing(db_session) -> None:
    """The same masked payload reaches the client on every tier — no raw names anywhere."""
    from valeri_api.llm.masking import MaskingContext, mask_text

    real_name = "Hotel Stari Grad — Objekat 1"
    context = MaskingContext()
    masked = mask_text(f"Pitanje o kupcu {real_name}.", [(real_name, 7, real_name)], context)
    payload = {"upit": masked}

    for role in ("simple_qa", "over_suppression_audit", "investigation_synthesis"):
        fake = AutoFakeLLMClient()
        narrate_structured(
            db_session,
            payload,
            _RoutedOutput,
            system_prompt=SYSTEM,
            instruction=INSTRUCTION,
            client=fake,
            role=role,
        )
        prompts = "\n".join(item["system"] + "\n" + item["user"] for item in fake.captured)
        assert real_name not in prompts, f"raw name leaked on role {role}"
        assert "Kupac-" in prompts


# ── prompt caching (cost lever) ───────────────────────────────────────────────


def test_prompt_cache_message_structure() -> None:
    """The system prompt is marked cacheable; disabling caching yields plain content."""
    client = LiteLLMClient(model="tier1")

    cached = client._build_messages(SYSTEM, "user pitanje", cache_system=True)
    assert cached[0]["role"] == "system"
    assert cached[0]["content"][0]["text"] == SYSTEM
    assert cached[0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert cached[1] == {"role": "user", "content": "user pitanje"}

    plain = client._build_messages(SYSTEM, "user pitanje", cache_system=False)
    assert plain[0] == {"role": "system", "content": SYSTEM}
