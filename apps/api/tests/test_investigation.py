"""M13 acceptance: the investigation agent (TDD — written before the implementation).

1. The loop cap is enforced (budget caps live in rule_config).
2. The HITL gate blocks an external draft/task until approval.
3. No number is computed by the model — rendered figures equal SQL/tool output.
4. A run resumes after a simulated restart from its Postgres checkpoint.
Plus: full step trace, masking inside the agent, RBAC through tools, the worker
poll, the status lifecycle, and the API surface.

All LLM calls are scripted fakes — no gateway needed. Runs are committed (the
agent runs in the worker, not in a request), so each test cleans up after itself.
"""

import datetime
import json
import re

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tests.conftest import login, make_client
from valeri_api.auth.models import AppUser
from valeri_api.llm.client import LLMResponse
from valeri_api.scanner.scan import run_scan
from valeri_api.seed.users import ADMIN_EMAIL, FINANCE_EMAIL, OWNER_EMAIL

# ── the scripted agent fake ───────────────────────────────────────────────────


class AgentFakeLLMClient:
    """One fake for all four agent roles, keyed off the system prompt.

    - plan → a fixed decomposition;
    - act → pops the next scripted ToolChoice (when the script runs out, 'done');
    - critic → pops the next scripted verdict (default 'dovoljno' when exhausted);
    - synthesize → a narrative that echoes ONLY numbers found in the prompt payload
      (mimicking a rule-following model), or a scripted override.
    """

    def __init__(
        self,
        tool_choices: list[dict] | None = None,
        verdicts: list[str] | None = None,
        synthesis_override: dict | None = None,
    ) -> None:
        self.tool_choices = list(tool_choices or [])
        self.verdicts = list(verdicts or [])
        self.synthesis_override = synthesis_override
        self.captured: list[dict[str, str]] = []
        self.model = "fake-tier2"

    def complete(self, system: str, user: str) -> LLMResponse:
        self.captured.append({"system": system, "user": user})

        if "rastaviš" in system:  # PLAN
            body = {
                "sub_questions": ["Koji je trend prometa?", "Koji signali postoje?"],
                "reasoning": "Pitanje treba podatke o prometu i otvorenim signalima.",
            }
        elif "Biraš SLJEDEĆI alat" in system:  # ACT
            if self.tool_choices:
                body = self.tool_choices.pop(0)
            else:
                body = {
                    "tool": None,
                    "params": {},
                    "reasoning": "Imam dovoljno podataka.",
                    "is_action_proposal": False,
                    "done": True,
                }
        elif "kritičar" in system:  # CRITIC
            verdict = self.verdicts.pop(0) if self.verdicts else "dovoljno"
            body = {
                "verdict": verdict,
                "reasoning": "Provjera nalaza prema dostupnim podacima.",
                "missing": [] if verdict == "dovoljno" else ["još podataka o prometu"],
            }
        elif "ZAVRŠNI izvještaj" in system:  # SYNTHESIZE
            if self.synthesis_override is not None:
                body = self.synthesis_override
            else:
                # Echo only numbers that exist in the prompt (the number contract holds).
                numbers = re.findall(r"-?\d+(?:\.\d+)?", user[user.find("{") :])
                echoed = f" Ključna vrijednost iz podataka: {numbers[0]}." if numbers else ""
                body = {
                    "narrative": (
                        "Istraga je analizirala dostupne podatke iz baze i utvrdila obrasce "
                        "u prometu i signalima." + echoed
                    ),
                    "findings": [
                        {
                            "text": "Podaci pokazuju obrazac koji zahtijeva pažnju vlasnika.",
                            "confidence": 0.8,
                        }
                    ],
                    "confidence": 0.8,
                    "next_step": "Kontaktirati kupce iz nalaza i pratiti promet.",
                }
        else:
            raise AssertionError(f"unexpected system prompt: {system[:80]}")

        return LLMResponse(
            text=json.dumps(body, ensure_ascii=False),
            model=self.model,
            tokens=120,
            latency_ms=40,
        )


# ── fixtures ──────────────────────────────────────────────────────────────────

BUDGET_DEFAULTS = {"max_steps": 8, "max_seconds": 300, "max_tokens": 50000}


def _reset_app_tables(session: Session) -> None:
    session.execute(
        text(
            "TRUNCATE app.investigation_step, app.investigation, "
            "audit.ai_log, audit.task_log, audit.llm_route_log, app.task_feedback, "
            "app.approval, app.owner_report, app.tool_call_log, app.message, app.conversation, "
            "app.suppression_hit, app.decision, app.task, app.signal, app.learned_rule "
            "RESTART IDENTITY CASCADE"
        )
    )


@pytest.fixture(scope="module")
def inv_db(db_engine: Engine, seed_data):
    """Seed + scan once for the module (committed); restore the seed afterwards."""
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


def _cleanup_runs(engine: Engine) -> None:
    """Remove committed investigation runs + agent-created tasks (between tests)."""
    with Session(engine) as session:
        session.execute(text("DELETE FROM app.investigation_step"))
        session.execute(text("DELETE FROM app.investigation"))
        # Agent-created tasks have signal_id IS NULL (create_task_draft).
        session.execute(
            text(
                "DELETE FROM audit.task_log WHERE task_id IN "
                "(SELECT id FROM app.task WHERE signal_id IS NULL)"
            )
        )
        session.execute(text("DELETE FROM app.task WHERE signal_id IS NULL"))
        # Restore the budget defaults (tests tighten them).
        for param, value in BUDGET_DEFAULTS.items():
            session.execute(
                text(
                    "UPDATE app.rule_config SET value = CAST(:value AS jsonb) "
                    "WHERE rule = 'investigation' AND param = :param"
                ),
                {"value": json.dumps(value), "param": param},
            )
        session.commit()


@pytest.fixture
def inv_env(inv_db):
    """Per-test environment: clean run state before and after."""
    engine, as_of = inv_db
    _cleanup_runs(engine)
    yield engine, as_of
    _cleanup_runs(engine)


def _owner(session: Session) -> AppUser:
    return session.query(AppUser).filter(AppUser.email == OWNER_EMAIL).one()


def _set_budget(engine: Engine, **caps) -> None:
    with Session(engine) as session:
        for param, value in caps.items():
            session.execute(
                text(
                    "UPDATE app.rule_config SET value = CAST(:value AS jsonb) "
                    "WHERE rule = 'investigation' AND param = :param"
                ),
                {"value": json.dumps(value), "param": param},
            )
        session.commit()


def _create_queued(engine: Engine, question: str, signal_id: int | None = None) -> int:
    """A queued investigation created by the owner (direct, not via API)."""
    from valeri_api.investigation.runner import create_investigation

    with Session(engine) as session:
        owner = _owner(session)
        investigation = create_investigation(session, question, owner, signal_id=signal_id)
        session.commit()
        return investigation.id


def _steps(engine: Engine, investigation_id: int) -> list:
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT step_no, node, tool, input, output FROM app.investigation_step "
                "WHERE investigation_id = :id ORDER BY step_no"
            ),
            {"id": investigation_id},
        ).all()


def _investigation(engine: Engine, investigation_id: int):
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT * FROM app.investigation WHERE id = :id"), {"id": investigation_id}
        ).one()


READ_TOOL_CHOICE = {
    "tool": "list_signals",
    "params": {"rule": "customer_decline", "limit": 5},
    "reasoning": "Trebam otvorene signale pada prometa.",
    "is_action_proposal": False,
    "done": False,
}


def _task_proposal(customer_id: int) -> dict:
    """A create_task_draft proposal referencing a customer by pseudonym (as the model would)."""
    from valeri_api.llm.masking import pseudonym

    return {
        "tool": "create_task_draft",
        "params": {
            "customer_ref": pseudonym(customer_id),
            "title": "Kontaktirati kupca zbog pada prometa",
        },
        "reasoning": "Vlasnik treba zadatak za komercijalistu.",
        "is_action_proposal": True,
        "done": False,
    }


def _any_customer(engine: Engine):
    """A seeded customer (id + name) the tests can reference in questions/proposals."""
    with engine.connect() as conn:
        return conn.execute(text("SELECT id, name FROM core.customer ORDER BY id LIMIT 1")).one()


# ── 1/2. the loop cap (acceptance 1) ──────────────────────────────────────────


def test_loop_cap_enforced(inv_env) -> None:
    """A critic that always wants more cannot loop past max_steps; the run still reports."""
    from valeri_api.investigation.runner import run_investigation

    engine, _ = inv_env
    _set_budget(engine, max_steps=3)

    # The act fake always has another tool to run; the critic always wants more.
    fake = AgentFakeLLMClient(
        tool_choices=[dict(READ_TOOL_CHOICE) for _ in range(20)],
        verdicts=["treba_jos"] * 20,
    )
    investigation_id = _create_queued(engine, "Zašto pada promet hotelskog segmenta?")
    result = run_investigation(investigation_id, client=fake)

    assert result.status == "done"
    # Exactly max_steps act executions — the cap is the scanner's, not the model's.
    act_steps = [step for step in _steps(engine, investigation_id) if step.node == "act"]
    assert len(act_steps) == 3
    # The report exists and says the budget was exhausted.
    assert result.report is not None
    assert result.report["budget_exhausted"] == "max_steps"
    assert result.report["confidence"] is not None


def test_budget_caps_live_in_rule_config(inv_env) -> None:
    """Lowering max_steps in the DB changes where the loop stops — nothing hard-coded."""
    from valeri_api.investigation.runner import run_investigation

    engine, _ = inv_env
    _set_budget(engine, max_steps=1)

    fake = AgentFakeLLMClient(
        tool_choices=[dict(READ_TOOL_CHOICE) for _ in range(5)],
        verdicts=["treba_jos"] * 5,
    )
    investigation_id = _create_queued(engine, "Koji kupci najviše doprinose padu prometa?")
    run_investigation(investigation_id, client=fake)

    act_steps = [step for step in _steps(engine, investigation_id) if step.node == "act"]
    assert len(act_steps) == 1


# ── 3. the HITL gate (acceptance 2) ───────────────────────────────────────────


def test_hitl_blocks_external_draft_until_approval(inv_env) -> None:
    """A proposed task draft does NOT exist until the human approves the resume."""
    from valeri_api.investigation.runner import resume_investigation, run_investigation

    engine, _ = inv_env
    customer = _any_customer(engine)

    fake = AgentFakeLLMClient(
        tool_choices=[dict(READ_TOOL_CHOICE), _task_proposal(customer.id)],
        verdicts=["treba_jos", "dovoljno"],
    )
    # The question names the customer → resolution registers its pseudonym in state,
    # so the approved action's customer_ref can be resolved back to the real id.
    investigation_id = _create_queued(
        engine, f"Šta uraditi povodom pada prometa kod kupca {customer.name}?"
    )
    result = run_investigation(investigation_id, client=fake)

    # ── the gate: the graph stopped before executing anything ────────────────
    assert result.status == "needs_input"
    with engine.connect() as conn:
        agent_tasks = conn.execute(
            text("SELECT COUNT(*) FROM app.task WHERE signal_id IS NULL")
        ).scalar()
    assert agent_tasks == 0, "NO task may exist before the human approves"

    # The proposal is visible in the trace (what the human is deciding about).
    proposals = [
        step for step in _steps(engine, investigation_id) if step.tool == "create_task_draft"
    ]
    assert len(proposals) == 1
    assert proposals[0].output["proposed_action"]["tool"] == "create_task_draft"

    # ── approve → the task now exists; the investigation completes ────────────
    resume_fake = AgentFakeLLMClient()  # synthesize only
    resumed = resume_investigation(investigation_id, "approve", client=resume_fake)
    assert resumed.status == "done"

    with engine.connect() as conn:
        agent_tasks_after = conn.execute(
            text("SELECT COUNT(*) FROM app.task WHERE signal_id IS NULL")
        ).scalar()
    assert agent_tasks_after == 1, "the approved action must now be executed"
    assert resumed.report is not None


def test_hitl_reject_discards_the_draft(inv_env) -> None:
    """Rejecting the proposal: the investigation completes but nothing was created."""
    from valeri_api.investigation.runner import resume_investigation, run_investigation

    engine, _ = inv_env
    customer = _any_customer(engine)

    fake = AgentFakeLLMClient(
        tool_choices=[_task_proposal(customer.id)],
        verdicts=["dovoljno"],
    )
    investigation_id = _create_queued(
        engine, f"Treba li kreirati zadatke za pad prometa kod kupca {customer.name}?"
    )
    result = run_investigation(investigation_id, client=fake)
    assert result.status == "needs_input"

    resumed = resume_investigation(investigation_id, "reject", client=AgentFakeLLMClient())
    assert resumed.status == "done"

    with engine.connect() as conn:
        agent_tasks = conn.execute(
            text("SELECT COUNT(*) FROM app.task WHERE signal_id IS NULL")
        ).scalar()
    assert agent_tasks == 0, "a rejected proposal must never execute"

    # The rejection is visible in the trace (nothing happens silently).
    reject_steps = [
        step
        for step in _steps(engine, investigation_id)
        if step.node == "execute_action" and (step.output or {}).get("decision") == "reject"
    ]
    assert len(reject_steps) == 1


# ── 4. numbers only from SQL (acceptance 3) ───────────────────────────────────


def test_numbers_only_from_sql(inv_env) -> None:
    """Report numbers come from tool outputs; invented numbers are rejected, never stored."""
    from valeri_api.investigation.runner import run_investigation

    engine, _ = inv_env

    # a) An honest synthesis (echoes prompt numbers) is accepted; every number in the
    #    stored narrative exists in the tool outputs.
    fake = AgentFakeLLMClient(tool_choices=[dict(READ_TOOL_CHOICE)], verdicts=["dovoljno"])
    investigation_id = _create_queued(engine, "Koliko signala pada prometa postoji?")
    result = run_investigation(investigation_id, client=fake)

    assert result.status == "done"
    assert result.report["narrative_source"] == "llm"

    # Collect every number in the stored report text and check it against tool outputs.
    from valeri_api.llm.masking import collect_allowed_numbers
    from valeri_api.llm.validators import check_number_contract

    act_outputs = [step.output for step in _steps(engine, investigation_id) if step.node == "act"]
    allowed = collect_allowed_numbers({"outputs": act_outputs, "q": result.question})
    report_text = " ".join(
        [result.report["narrative"]]
        + [finding["text"] for finding in result.report["findings"]]
        + [result.report["next_step"]]
    )
    assert check_number_contract(report_text, allowed) == []

    _cleanup_runs(engine)

    # b) A synthesis that INVENTS a number is rejected → deterministic template instead.
    inventing_fake = AgentFakeLLMClient(
        tool_choices=[dict(READ_TOOL_CHOICE)],
        verdicts=["dovoljno"],
        synthesis_override={
            "narrative": (
                "Promet je pao za tačno 98765.43 KM što je izmišljena vrijednost koja ne "
                "postoji u podacima alata."
            ),
            "findings": [{"text": "Izmišljeni nalaz bez pokrića u podacima.", "confidence": 0.9}],
            "confidence": 0.9,
            "next_step": "Ovo ne smije biti sačuvano kao LLM izvještaj.",
        },
    )
    investigation_id_b = _create_queued(engine, "Koliki je tačan iznos pada prometa?")
    result_b = run_investigation(investigation_id_b, client=inventing_fake)

    assert result_b.status == "done"
    assert result_b.report["narrative_source"] == "template"
    assert "98765.43" not in json.dumps(result_b.report)


# ── 5. checkpoint resume after a simulated restart (acceptance 4) ─────────────


def test_resume_after_simulated_restart(inv_env) -> None:
    """A new process (new graph + checkpointer instances) resumes; old steps don't re-run."""
    from valeri_api.investigation.runner import resume_investigation, run_investigation

    engine, _ = inv_env
    customer = _any_customer(engine)

    fake = AgentFakeLLMClient(
        tool_choices=[dict(READ_TOOL_CHOICE), _task_proposal(customer.id)],
        verdicts=["treba_jos", "dovoljno"],
    )
    investigation_id = _create_queued(
        engine, f"Kako zaustaviti pad prometa kod kupca {customer.name}?"
    )
    result = run_investigation(investigation_id, client=fake)
    assert result.status == "needs_input"

    # Snapshot the pre-restart state of the world.
    steps_before = _steps(engine, investigation_id)
    with engine.connect() as conn:
        tool_calls_before = conn.execute(text("SELECT COUNT(*) FROM app.tool_call_log")).scalar()

    # "Restart": resume_investigation builds a BRAND NEW graph + checkpointer (by design,
    # every invocation does) — the run continues from the Postgres checkpoint.
    resumed = resume_investigation(investigation_id, "approve", client=AgentFakeLLMClient())
    assert resumed.status == "done"
    assert resumed.report is not None

    steps_after = _steps(engine, investigation_id)
    # The pre-interrupt steps were NOT re-executed: they are a strict prefix.
    assert [(step.step_no, step.node) for step in steps_after[: len(steps_before)]] == [
        (step.step_no, step.node) for step in steps_before
    ]
    # Only the post-interrupt work was added (hitl + execute_action + synthesize).
    new_nodes = [step.node for step in steps_after[len(steps_before) :]]
    assert "execute_action" in new_nodes
    assert "synthesize" in new_nodes
    assert "plan" not in new_nodes and "act" not in new_nodes

    # The read-only tool calls from before the restart were not repeated
    # (only the approved action's dispatch was added).
    with engine.connect() as conn:
        tool_calls_after = conn.execute(text("SELECT COUNT(*) FROM app.tool_call_log")).scalar()
    assert tool_calls_after == tool_calls_before + 1


# ── 6. the full trace ─────────────────────────────────────────────────────────


def test_full_step_trace(inv_env) -> None:
    """Every node execution appends exactly one ordered investigation_step row."""
    from valeri_api.investigation.runner import run_investigation

    engine, _ = inv_env
    fake = AgentFakeLLMClient(tool_choices=[dict(READ_TOOL_CHOICE)], verdicts=["dovoljno"])
    investigation_id = _create_queued(engine, "Kakvo je stanje signala u sistemu danas?")
    run_investigation(investigation_id, client=fake)

    steps = _steps(engine, investigation_id)
    nodes = [step.node for step in steps]
    assert nodes == ["plan", "act", "critic", "synthesize"]
    assert [step.step_no for step in steps] == [1, 2, 3, 4]
    # The act step records the tool + masked input + output.
    act = steps[1]
    assert act.tool == "list_signals"
    assert act.output["ok"] is True


# ── 7. masking inside the agent ───────────────────────────────────────────────


def test_agent_prompts_are_masked(inv_env, seed_data) -> None:
    """No raw customer name reaches any agent prompt; the stored report is rehydrated."""
    from valeri_api.investigation.runner import run_investigation

    engine, _ = inv_env

    # Pick a real customer that has a decline signal (it will appear in tool output).
    with Session(engine) as session:
        customer = session.execute(
            text(
                "SELECT c.id, c.name FROM app.signal s "
                "JOIN core.customer c ON c.id = s.customer_id "
                "WHERE s.rule = 'customer_decline' AND s.status = 'tasked' "
                "ORDER BY s.id LIMIT 1"
            )
        ).one()

    fake = AgentFakeLLMClient(
        tool_choices=[
            {
                "tool": "get_customer_360",
                "params": {"customer_ref": "{{KUPAC}}"},  # replaced below via the masked question
                "reasoning": "Trebam profil kupca.",
                "is_action_proposal": False,
                "done": False,
            }
        ],
        verdicts=["dovoljno"],
    )

    # The question names the customer → resolution + masking happen in the runner.
    question = f"Zašto kupac {customer.name} ima pad prometa?"
    investigation_id = _create_queued(engine, question)

    # The act fake needs the customer's pseudonym as customer_ref: patch the choice
    # right before running, using the pseudonym deterministically derived from the id.
    from valeri_api.llm.masking import pseudonym

    fake.tool_choices[0]["params"]["customer_ref"] = pseudonym(customer.id)

    result = run_investigation(investigation_id, client=fake)
    assert result.status == "done"

    # No prompt contains the real name; pseudonyms appear instead.
    all_prompts = "\n".join(item["system"] + "\n" + item["user"] for item in fake.captured)
    assert customer.name not in all_prompts
    assert "Kupac-" in all_prompts

    # The stored report is human-facing: the real name is back (rehydrated).
    report_json = json.dumps(result.report, ensure_ascii=False)
    assert "Kupac-" not in report_json

    # The step trace inputs/outputs are masked (they feed prompts).
    for step in _steps(engine, investigation_id):
        if step.node in ("plan", "act", "critic"):
            assert customer.name not in json.dumps(step.input or {}, ensure_ascii=False)
            assert customer.name not in json.dumps(step.output or {}, ensure_ascii=False)


# ── 8. RBAC flows through the agent's tools ───────────────────────────────────


def test_agent_tools_respect_rbac(inv_env, seed_data) -> None:
    """An investigation created by a rep fails closed on out-of-scope customers."""
    from valeri_api.investigation.models import Investigation
    from valeri_api.investigation.runner import run_investigation
    from valeri_api.llm.masking import pseudonym

    engine, _ = inv_env

    # A rep + a customer that does NOT belong to that rep.
    rep_user = next(user for user in seed_data.app_users if user["role"] == "sales_rep")
    with Session(engine) as session:
        foreign_customer = session.execute(
            text(
                "SELECT c.id, c.name FROM core.customer c JOIN ("
                "  SELECT DISTINCT ON (customer_id) customer_id, sales_rep_id "
                "  FROM core.customer_rep ORDER BY customer_id, from_date DESC"
                ") cur ON cur.customer_id = c.id WHERE cur.sales_rep_id != :rep_id LIMIT 1"
            ),
            {"rep_id": rep_user["sales_rep_id"]},
        ).one()

        # Create the investigation AS THE REP (directly — the API only allows owner/admin).
        investigation = Investigation(
            trigger="user",
            question=f"Kakav je profil kupca {foreign_customer.name}?",
            status="queued",
            model_tier="tier2",
            created_by=rep_user["id"],
            thread_id="rbac-test-thread",
        )
        session.add(investigation)
        session.commit()
        investigation_id = investigation.id

    fake = AgentFakeLLMClient(
        tool_choices=[
            {
                "tool": "get_customer_360",
                "params": {"customer_ref": pseudonym(foreign_customer.id)},
                "reasoning": "Trebam profil kupca.",
                "is_action_proposal": False,
                "done": False,
            }
        ],
        verdicts=["dovoljno"],
    )
    result = run_investigation(investigation_id, client=fake)

    # The run completes (it doesn't crash) but the tool call failed closed.
    assert result.status == "done"
    act_steps = [step for step in _steps(engine, investigation_id) if step.node == "act"]
    assert act_steps[0].output["ok"] is False


# ── 9/10. the worker + the status lifecycle ───────────────────────────────────


def test_worker_picks_up_queued(inv_env) -> None:
    """poll_queued() runs the oldest queued investigation; the scheduler has the job."""
    from valeri_api.investigation.runner import poll_queued
    from valeri_api.scanner.scheduler import create_scheduler

    engine, _ = inv_env
    fake = AgentFakeLLMClient(verdicts=["dovoljno"])
    investigation_id = _create_queued(engine, "Da li postoje neobični obrasci u prodaji?")

    picked_up = poll_queued(client=fake)
    assert picked_up == investigation_id
    assert _investigation(engine, investigation_id).status == "done"

    # Nothing left in the queue → poll returns None.
    assert poll_queued(client=fake) is None

    # The worker schedule includes the poll job.
    scheduler = create_scheduler()
    job_ids = {job.id for job in scheduler.get_jobs()}
    assert "investigation_poll" in job_ids


def test_failed_run_is_visible(inv_env) -> None:
    """A crashing node → status 'failed' + the error in the trace (never silent)."""
    from valeri_api.investigation.runner import run_investigation

    engine, _ = inv_env

    class ExplodingClient:
        model = "fake-tier2"

        def complete(self, system: str, user: str) -> LLMResponse:
            raise RuntimeError("simulirani pad agenta")

    investigation_id = _create_queued(engine, "Ova istraga će namjerno pasti zbog testa.")
    result = run_investigation(investigation_id, client=ExplodingClient())

    assert result.status == "failed"
    error_steps = [step for step in _steps(engine, investigation_id) if step.node == "error"]
    assert len(error_steps) == 1
    assert "simulirani pad agenta" in json.dumps(error_steps[0].output)


# ── 11/12. the API surface ────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_api_create_list_detail_resume_rbac(inv_env, monkeypatch) -> None:
    """The four JSON endpoints + RBAC + envelopes, with the runner exercised via fakes."""
    from valeri_api.investigation.runner import run_investigation

    engine, _ = inv_env

    owner_client = make_client()
    finance_client = make_client()
    try:
        await login(owner_client, OWNER_EMAIL)
        await login(finance_client, FINANCE_EMAIL)

        # ── create (owner) → 202 queued ───────────────────────────────────────
        created = await owner_client.post(
            "/api/investigations",
            json={"question": "Zašto pada promet u hotelskom segmentu zadnja tri mjeseca?"},
        )
        assert created.status_code == 202, created.text
        investigation_id = created.json()["investigation_id"]
        assert created.json()["status"] == "queued"

        # ── finance cannot create; can read ───────────────────────────────────
        denied = await finance_client.post(
            "/api/investigations", json={"question": "Finansije ne pokreću istrage nikada."}
        )
        assert denied.status_code == 403
        assert (await finance_client.get("/api/investigations")).status_code == 200

        # ── list shows it as queued ───────────────────────────────────────────
        listing = await owner_client.get("/api/investigations", params={"status": "queued"})
        assert any(item["id"] == investigation_id for item in listing.json()["items"])

        # ── run it (the worker would do this) with a proposal → needs_input ──
        customer = _any_customer(engine)
        fake = AgentFakeLLMClient(
            tool_choices=[dict(READ_TOOL_CHOICE), _task_proposal(customer.id)],
            verdicts=["treba_jos", "dovoljno"],
        )
        run_investigation(investigation_id, client=fake)

        # ── detail: needs_input + pending actions visible ─────────────────────
        detail = await owner_client.get(f"/api/investigations/{investigation_id}")
        assert detail.status_code == 200
        body = detail.json()
        assert body["investigation"]["status"] == "needs_input"
        assert len(body["pending_actions"]) == 1
        assert body["pending_actions"][0]["tool"] == "create_task_draft"
        assert len(body["steps"]) >= 4

        # ── resume RBAC: finance cannot decide ────────────────────────────────
        finance_resume = await finance_client.post(
            f"/api/investigations/{investigation_id}/resume", json={"decision": "approve"}
        )
        assert finance_resume.status_code == 403

        # ── resume (owner, approve): the API path runs the production client
        #    factory → patch it so the post-resume synthesis uses a fake ────────
        resume_fake = AgentFakeLLMClient()
        monkeypatch.setattr("valeri_api.llm.structured.get_llm_client", lambda: resume_fake)
        resumed = await owner_client.post(
            f"/api/investigations/{investigation_id}/resume", json={"decision": "approve"}
        )
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["investigation"]["status"] == "done"

        # ── resume again → 409 (not waiting any more) ─────────────────────────
        again = await owner_client.post(
            f"/api/investigations/{investigation_id}/resume", json={"decision": "approve"}
        )
        assert again.status_code == 409

        # ── detail now carries the report ─────────────────────────────────────
        final_detail = await owner_client.get(f"/api/investigations/{investigation_id}")
        assert final_detail.json()["report"] is not None
        assert final_detail.json()["report"]["register"] == "analiza"

        # ── 404 envelope ──────────────────────────────────────────────────────
        missing = await owner_client.get("/api/investigations/999999")
        assert missing.status_code == 404
    finally:
        await owner_client.aclose()
        await finance_client.aclose()


@pytest.mark.anyio
async def test_api_sse_stream(inv_env) -> None:
    """The SSE endpoint emits step events and closes on a terminal status."""
    from valeri_api.investigation.runner import run_investigation

    engine, _ = inv_env

    admin_client = make_client()
    try:
        await login(admin_client, ADMIN_EMAIL)

        created = await admin_client.post(
            "/api/investigations",
            json={"question": "Kakvi su trendovi prometa u zadnjem kvartalu?"},
        )
        investigation_id = created.json()["investigation_id"]

        # Complete the run first; the stream then replays steps and closes.
        fake = AgentFakeLLMClient(tool_choices=[dict(READ_TOOL_CHOICE)], verdicts=["dovoljno"])
        run_investigation(investigation_id, client=fake)

        async with admin_client.stream(
            "GET", f"/api/investigations/{investigation_id}/stream"
        ) as response:
            assert response.status_code == 200
            events = []
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[len("data: ") :]))

        types = [event["type"] for event in events]
        assert "step" in types
        assert types[-1] == "done"
        # Step events carry the node names in order.
        step_nodes = [event["node"] for event in events if event["type"] == "step"]
        assert step_nodes == ["plan", "act", "critic", "synthesize"]
    finally:
        await admin_client.aclose()
