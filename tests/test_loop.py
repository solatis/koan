# Tests for koan.agents.loop -- the in-process multi-turn agent loop.
#
# Two layers:
#   - Pure-helper tests for assemble_resume_prompt / _yolo_yield_response /
#     _directed_yolo_response / drain_and_render_steering (deterministic, no model).
#   - resolve_turn_outcome unit tests (step-machine outcome logic).
#   - Integration tests that drive PydanticAIAgent.run() (which delegates to
#     run_agent_loop) with pydantic-ai's TestModel, covering the four control-flow
#     paths: non-primary single turn, workflow_done termination, primary
#     park/resume, and yolo synthesis-without-parking.
#
# With the M6 per-step-turn model, each turn delivers one step. The fake phase
# module uses get_next_step=None (phase exhausted after step 1) so the resolver
# terminates non-primary agents and parks primary agents after their first turn.

from __future__ import annotations

import asyncio
from contextlib import contextmanager

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from koan.agents.base import AgentOptions
from koan.agents.pydantic_ai import PydanticAIAgent
from koan.agents.loop import (
    _directed_yolo_response,
    _yolo_yield_response,
    assemble_resume_prompt,
    drain_and_render_steering,
    resolve_turn_outcome,
)
from koan.phases import PhaseContext, StepGuidance
from koan.state import AgentState, AppState, ChatMessage
from koan.types import ModelSpec


# -- Pure helpers --------------------------------------------------------------


def test_yolo_yield_response_prefers_recommended_non_done():
    suggestions = [
        {"id": "done", "command": "stop"},
        {"id": "plan", "command": "write the plan", "recommended": True},
    ]
    assert _yolo_yield_response(suggestions) == "write the plan"


def test_yolo_yield_response_falls_back_to_first_non_done_then_proceed():
    assert _yolo_yield_response([{"id": "execute", "command": "go"}]) == "go"
    assert _yolo_yield_response([{"id": "done", "command": "stop"}]) == "proceed"
    assert _yolo_yield_response(None) == "proceed"


def test_directed_yolo_response_steers_to_next_phase():
    directed = ["intake", "plan", "execute", "done"]
    assert "plan" in _directed_yolo_response(directed, "intake")
    # Last real phase -> done tombstone instruction.
    assert 'koan_set_phase("done")' in _directed_yolo_response(directed, "execute")
    # Unknown current phase -> proceed.
    assert _directed_yolo_response(directed, "nope") == "proceed"


def test_assemble_resume_prompt_empty_is_proceed():
    prompt, manifest = assemble_resume_prompt([], AppState(), "pydantic_ai")
    assert prompt == "proceed"
    assert manifest == []


def test_assemble_resume_prompt_wraps_user_message():
    msgs = [ChatMessage(content="do the thing", timestamp_ms=1)]
    prompt, manifest = assemble_resume_prompt(msgs, AppState(), "pydantic_ai")
    assert "USER MESSAGE" in prompt
    assert "do the thing" in prompt
    assert manifest == []  # no attachments


def test_build_phase_suggestions_from_workflow():
    """M7.5: hand-back suggestions are derived from the workflow transitions."""
    from koan.lib.workflows import build_phase_suggestions, get_workflow
    wf = get_workflow("plan")
    sugg = build_phase_suggestions(wf, wf.initial_phase)
    assert sugg, "expected at least the 'done' option"
    assert all({"id", "label", "phase"} <= set(s) for s in sugg)
    ids = [s["id"] for s in sugg]
    assert ids[-1] == "done"  # terminal option always last


def test_drain_and_render_steering_emits_event_and_text():
    app_state = AppState()
    agent = AgentState(agent_id="a", role="orchestrator", subagent_dir="", is_primary=True)
    app_state.interactions.steering_queue.append(
        ChatMessage(content="reconsider the auth flow", timestamp_ms=1)
    )
    text = drain_and_render_steering(app_state, agent)
    assert text is not None
    assert "reconsider the auth flow" in text
    # Queue drained.
    assert app_state.interactions.steering_queue == []
    # steering_delivered projection event emitted.
    events = app_state.projection_store.events
    assert any(e.event_type == "steering_delivered" for e in events)
    # Non-primary agents do not drain.
    assert drain_and_render_steering(app_state, None) is None


# -- resolve_turn_outcome unit tests ------------------------------------------


def _fake_phase_module_exhausted() -> MagicMock:
    """Phase module whose steps are exhausted after step 1 (get_next_step=None)."""
    mod = MagicMock()
    mod.ROLE = "orchestrator"
    mod.TOTAL_STEPS = 1
    mod.PHASE_ROLE_CONTEXT = ""
    mod.STEP_NAMES = {1: "Comprehend"}
    mod.validate_step_completion = MagicMock(return_value=None)
    mod.get_next_step = MagicMock(return_value=None)
    mod.step_guidance = MagicMock(return_value=StepGuidance(
        title="Comprehend", instructions=["Read the brief."],
    ))
    mod.on_loop_back = AsyncMock()
    return mod


def _make_agent_state(
    tmp_dir: str,
    *,
    is_primary: bool = True,
    step: int = 1,
    phase_module=None,
) -> tuple[AppState, AgentState]:
    """Build a minimal AppState + AgentState pair for resolver tests."""
    app_state = AppState()
    app_state.run.phase = "intake"
    app_state.run.workflow = None
    event_log = AsyncMock()
    event_log.emit_step_transition = AsyncMock()
    agent = AgentState(
        agent_id="resolver-test",
        role="orchestrator",
        subagent_dir=tmp_dir,
        run_dir="",
        step=step,
        phase_module=phase_module or _fake_phase_module_exhausted(),
        phase_ctx=PhaseContext(run_dir="", subagent_dir=tmp_dir),
        event_log=event_log,
        is_primary=is_primary,
        runner_type="pydantic_ai",
    )
    app_state.agents[agent.agent_id] = agent
    return app_state, agent


@pytest.mark.anyio
async def test_resolver_step_zero_injects_handshake(tmp_path):
    """step==0 triggers the phase handshake and returns an inject outcome."""
    app_state, agent = _make_agent_state(str(tmp_path), step=0)
    outcome, payload = await resolve_turn_outcome(agent, app_state)
    assert outcome == "inject"
    assert payload is not None and len(payload) > 0
    # Handshake sets agent.step to 1.
    assert agent.step == 1


@pytest.mark.anyio
async def test_resolver_mid_phase_step_advances(tmp_path):
    """A mid-phase step with a further step returns inject with the next guidance."""
    mod = _fake_phase_module_exhausted()
    mod.get_next_step = MagicMock(return_value=2)  # further step exists
    mod.TOTAL_STEPS = 3
    mod.STEP_NAMES = {1: "Comprehend", 2: "Plan", 3: "Write"}
    app_state, agent = _make_agent_state(str(tmp_path), step=1, phase_module=mod)
    outcome, payload = await resolve_turn_outcome(agent, app_state)
    assert outcome == "inject"
    assert payload is not None
    # Step advances to 2.
    assert agent.step == 2


@pytest.mark.anyio
async def test_resolver_phase_exhausted_primary_returns_handback(tmp_path):
    """Phase exhausted + is_primary=True -> handback outcome."""
    app_state, agent = _make_agent_state(str(tmp_path), is_primary=True, step=1)
    # get_next_step returns None (exhausted).
    outcome, payload = await resolve_turn_outcome(agent, app_state)
    assert outcome == "handback"
    assert payload is None


@pytest.mark.anyio
async def test_resolver_phase_exhausted_non_primary_returns_terminate(tmp_path):
    """Phase exhausted + is_primary=False -> terminate outcome."""
    app_state, agent = _make_agent_state(str(tmp_path), is_primary=False, step=1)
    outcome, payload = await resolve_turn_outcome(agent, app_state)
    assert outcome == "terminate"
    assert payload is None


@pytest.mark.anyio
async def test_resolver_validation_failure_reinjects_same_step(tmp_path):
    """Non-empty validate_step_completion re-injects the same step."""
    mod = _fake_phase_module_exhausted()
    mod.validate_step_completion = MagicMock(return_value="Must write landscape.md first")
    app_state, agent = _make_agent_state(str(tmp_path), step=1, phase_module=mod)
    outcome, payload = await resolve_turn_outcome(agent, app_state)
    assert outcome == "inject"
    assert "Must write landscape.md first" in (payload or "")
    # Step does NOT advance on validation failure.
    assert agent.step == 1


# -- Integration harness -------------------------------------------------------


def _fake_phase_module(total_steps: int = 3) -> MagicMock:
    """Phase module with steps exhausted after step 1 (for integration tests).

    get_next_step returns None so the resolver terminates non-primary agents
    and parks primary agents after their first step -- the expected M6 behaviour.
    """
    mod = MagicMock()
    mod.ROLE = "orchestrator"
    mod.TOTAL_STEPS = total_steps
    mod.PHASE_ROLE_CONTEXT = ""
    mod.STEP_NAMES = {1: "Comprehend", 2: "Plan", 3: "Write"}
    mod.validate_step_completion = MagicMock(return_value=None)
    mod.get_next_step = MagicMock(return_value=None)  # exhausted after step 1
    mod.step_guidance = MagicMock(return_value=StepGuidance(
        title="Comprehend", instructions=["Read the brief."],
    ))
    mod.on_loop_back = AsyncMock()
    return mod


def _make(agent_id: str, tmp_dir: str, is_primary: bool) -> tuple[AppState, AgentState]:
    app_state = AppState()
    app_state.run.phase = "intake"
    app_state.run.workflow = None
    event_log = AsyncMock()
    event_log.emit_step_transition = AsyncMock()
    agent = AgentState(
        agent_id=agent_id,
        role="orchestrator",
        subagent_dir=tmp_dir,
        run_dir="",
        step=0,
        phase_module=_fake_phase_module(),
        phase_ctx=PhaseContext(run_dir="", subagent_dir=tmp_dir),
        event_log=event_log,
        is_primary=is_primary,
        runner_type="pydantic_ai",
    )
    app_state.agents[agent_id] = agent
    return app_state, agent


@contextmanager
def _test_model(call_tools):
    """Patch the adapter so the agent runs against TestModel (no network)."""
    from pydantic_ai.models.test import TestModel
    import koan.agents.adapter as adapter_mod
    orig_bm, orig_bms = adapter_mod.build_model, adapter_mod.build_model_settings
    adapter_mod.build_model = lambda spec, api_key=None, **_: TestModel(
        call_tools=call_tools, custom_output_text="done for now",
    )
    adapter_mod.build_model_settings = lambda spec: {}
    try:
        yield
    finally:
        adapter_mod.build_model = orig_bm
        adapter_mod.build_model_settings = orig_bms


def _agent(app_state: AppState, tmp_path) -> PydanticAIAgent:
    spec = ModelSpec(provider="google", model="gemini-2.0-flash", thinking="disabled")
    return PydanticAIAgent(model_spec=spec, app_state=app_state, subagent_dir=str(tmp_path))


def _options(agent_id: str) -> AgentOptions:
    """Build AgentOptions without boot_prompt (removed in M6)."""
    return AgentOptions(
        role="orchestrator", agent_id=agent_id, model=None, thinking=None,
        system_prompt="",
    )


# -- Integration: control-flow paths -------------------------------------------


@pytest.mark.anyio
async def test_non_primary_runs_single_turn_no_park(tmp_path):
    """A non-primary agent runs exactly one turn and returns without parking.

    With the M6 resolver: bootstrap sets step=1, model runs turn 1, resolver
    finds get_next_step=None -> terminate. One turn_complete, no park.
    """
    app_state, _ = _make("loop-np", str(tmp_path), is_primary=False)
    with _test_model(call_tools=[]):
        events = [ev async for ev in _agent(app_state, tmp_path).run(_options("loop-np"))]
    assert len([e for e in events if e.type == "turn_complete"]) == 1
    assert app_state.interactions.yield_future is None  # never parked


@pytest.mark.anyio
async def test_workflow_done_terminates_primary_without_parking(tmp_path):
    """workflow_done set before the run -> a primary agent runs one turn and
    returns at the post-turn termination check, never reaching the hand-back.

    Bootstrap still runs (sets step=1), but workflow_done is checked before the
    resolver so the loop returns without parking.
    """
    app_state, _ = _make("loop-done", str(tmp_path), is_primary=True)
    app_state.run.workflow_done = True
    with _test_model(call_tools=[]):
        events = [ev async for ev in _agent(app_state, tmp_path).run(_options("loop-done"))]
    assert len([e for e in events if e.type == "turn_complete"]) == 1
    assert app_state.interactions.yield_future is None


@pytest.mark.anyio
async def test_primary_parks_then_resumes_then_terminates(tmp_path):
    """A primary agent parks on yield_future when steps are exhausted,
    resumes with the buffered user message on resolution, and terminates once
    workflow_done is set. Asserts >= 2 turns and that history accumulated.

    With M6: resolver returns handback after step 1 (get_next_step=None).
    """
    app_state, agent_state = _make("loop-pr", str(tmp_path), is_primary=True)
    events = []

    async def consume(run_iter):
        async for ev in run_iter:
            events.append(ev)

    with _test_model(call_tools=[]):
        run_iter = _agent(app_state, tmp_path).run(_options("loop-pr"))
        task = asyncio.create_task(consume(run_iter))

        # Wait for the loop to park (turn 1 hand-back).
        for _ in range(500):
            if app_state.interactions.yield_future is not None:
                break
            await asyncio.sleep(0.005)
        assert app_state.interactions.yield_future is not None, "loop did not park"

        # Buffer a reply and arrange termination after the resumed turn.
        app_state.interactions.user_message_buffer.append(
            ChatMessage(content="keep going", timestamp_ms=1)
        )
        app_state.run.workflow_done = True
        app_state.interactions.yield_future.set_result(None)

        await asyncio.wait_for(task, timeout=10)

    assert len([e for e in events if e.type == "turn_complete"]) >= 2
    assert agent_state.message_history, "message_history should accumulate across turns"
    # A yield_started event marks the hand-back.
    assert any(e.event_type == "yield_started" for e in app_state.projection_store.events)


@pytest.mark.anyio
async def test_partstart_first_chunk_emitted(tmp_path):
    """The leading text chunk in PartStartEvent is emitted as the opening delta.

    Regression: Gemini ships the first text chunk inside PartStartEvent(TextPart)
    rather than a follow-up PartDeltaEvent. The streamed view accumulates
    token_delta content, so dropping the PartStartEvent chunk truncates the
    first characters of every text block. This drives a FunctionModel whose
    stream yields the opening chunk via PartStartEvent and asserts the
    concatenated token_delta stream reproduces the full text intact.
    """
    from pydantic_ai.models.function import FunctionModel
    import koan.agents.adapter as adapter_mod
    from koan.agents.events import StreamEvent

    full_text = "To make sure I'm helping effectively, could you clarify?"
    # FunctionModel places the first yielded string in PartStartEvent(TextPart).content
    # and the remaining strings as PartDeltaEvent(TextPartDelta) events.
    chunks = ["To make sure ", "I'm helping ", "effectively, ", "could you clarify?"]

    async def stream_func(messages, info):
        """Yield chunks so the first arrives via PartStartEvent, rest via PartDeltaEvent."""
        for chunk in chunks:
            yield chunk

    app_state, _ = _make("partstart-test", str(tmp_path), is_primary=False)

    orig_bm = adapter_mod.build_model
    orig_bms = adapter_mod.build_model_settings
    adapter_mod.build_model = lambda s, api_key=None, **_: FunctionModel(stream_function=stream_func)
    adapter_mod.build_model_settings = lambda s: {}
    try:
        events: list[StreamEvent] = [
            ev async for ev in _agent(app_state, tmp_path).run(_options("partstart-test"))
        ]
    finally:
        adapter_mod.build_model = orig_bm
        adapter_mod.build_model_settings = orig_bms

    streamed = "".join(e.content or "" for e in events if e.type == "token_delta")
    assert streamed == full_text, (
        f"streamed token_delta text must reproduce the full text without losing "
        f"the leading chunk; got {streamed!r}"
    )


@pytest.mark.anyio
async def test_retry_prompt_part_emits_tool_failed_event(tmp_path):
    """A tool call whose args fail validation emits tool_failed, not tool_result.

    Drives a FunctionModel that first calls koan_ask_question with questions as
    a JSON string (the production glm-5.2 payload; list[dict] expected), which
    pydantic-ai rejects with a RetryPromptPart, then answers with plain text on
    the retry request. The loop must translate the RetryPromptPart into a
    tool_failed StreamEvent carrying the human-readable validation error.
    """
    from pydantic_ai.messages import RetryPromptPart
    from pydantic_ai.models.function import DeltaToolCall, FunctionModel
    import koan.agents.adapter as adapter_mod
    from koan.agents.events import StreamEvent

    async def stream_func(messages, info):
        has_retry = any(
            isinstance(part, RetryPromptPart)
            for msg in messages for part in getattr(msg, "parts", [])
        )
        if has_retry:
            yield "recovered"
        else:
            yield {0: DeltaToolCall(
                name="koan_ask_question",
                json_args='{"questions": "not a list"}',
                tool_call_id="bad1",
            )}

    app_state, _ = _make("tool-failed-test", str(tmp_path), is_primary=False)

    orig_bm = adapter_mod.build_model
    orig_bms = adapter_mod.build_model_settings
    adapter_mod.build_model = lambda s, api_key=None, **_: FunctionModel(stream_function=stream_func)
    adapter_mod.build_model_settings = lambda s: {}
    try:
        events: list[StreamEvent] = [
            ev async for ev in _agent(app_state, tmp_path).run(_options("tool-failed-test"))
        ]
    finally:
        adapter_mod.build_model = orig_bm
        adapter_mod.build_model_settings = orig_bms

    failed = [e for e in events if e.type == "tool_failed"]
    assert len(failed) == 1
    assert failed[0].tool_name == "koan_ask_question"
    assert failed[0].tool_use_id == "bad1"
    assert "validation error" in (failed[0].content or "")
    # The failed call must NOT also surface as tool_result.
    assert not [e for e in events if e.type == "tool_result" and e.tool_use_id == "bad1"]
    assert any(e.type == "turn_complete" for e in events)


@pytest.mark.anyio
async def test_yolo_primary_synthesizes_without_parking(tmp_path, monkeypatch):
    """Under yolo, a primary agent never parks -- it synthesizes the next prompt.
    The yolo helper is patched to set workflow_done so the loop terminates after
    the second turn instead of synthesizing forever.

    With M6: resolver returns handback when steps exhausted; hand-back block
    calls _yolo_yield_response(suggestions) (not None) before resuming.
    """
    app_state, _ = _make("loop-yolo", str(tmp_path), is_primary=True)
    app_state.server.yolo = True

    def _fake_yolo(suggestions):
        # Terminate after the next turn's End-node check.
        app_state.run.workflow_done = True
        return "proceed"

    monkeypatch.setattr("koan.agents.loop._yolo_yield_response", _fake_yolo)

    with _test_model(call_tools=[]):
        events = [ev async for ev in _agent(app_state, tmp_path).run(_options("loop-yolo"))]

    assert app_state.interactions.yield_future is None, "yolo must not park"
    assert len([e for e in events if e.type == "turn_complete"]) >= 2


@pytest.mark.anyio
async def test_phase_transition_resets_context(tmp_path):
    """step==0 transition clears prior-phase history and re-injects new phase's artifacts.

    Guards the phase-boundary context-reset invariant: after _step_phase_handshake_core
    runs (via resolve_turn_outcome with step==0), the prior conversation is gone and
    only the new phase's injected artifact message(s) and listing message remain.
    """
    from pydantic_ai.messages import ModelRequest, UserPromptPart

    from koan.tools.handoff_artifacts import preseed_pending_artifacts, preseed_pending_listing

    # Write brief.md into a tmp run directory so preseed can inject it.
    run_dir = str(tmp_path)
    (tmp_path / "brief.md").write_text("# Brief content")

    app_state, agent = _make_agent_state(str(tmp_path), step=0)
    app_state.run.run_dir = run_dir
    agent.run_dir = run_dir

    # Inject some prior-phase content so the reset has something to clear.
    agent.message_history = [
        ModelRequest(parts=[UserPromptPart(content="prior phase turn 1")]),
        ModelRequest(parts=[UserPromptPart(content="prior phase turn 2")]),
    ]
    agent.injected_artifacts = {"brief.md"}  # previously injected; reset must clear

    # Simulate a phase module with required_artifacts including brief.md.
    from koan.lib.workflows import get_workflow
    workflow = get_workflow("plan")
    app_state.run.workflow = workflow
    app_state.run.phase = "plan"  # plan phase requires brief.md

    # Drive the step==0 path: invokes _step_phase_handshake_core -> reset_phase_context.
    outcome, _ = await resolve_turn_outcome(agent, app_state)
    assert outcome == "inject"

    # After the handshake, injected_artifacts was cleared by reset and
    # pending_artifacts was repopulated with brief.md for re-injection.
    # Now drain them (as run_agent_loop does at the top of the while loop).
    preseed_pending_artifacts(agent, app_state)
    preseed_pending_listing(agent)

    # Prior-phase messages must be gone.
    contents = [msg.parts[0].content for msg in agent.message_history]
    assert not any("prior phase turn" in c for c in contents), (
        "prior-phase messages must be cleared by the context reset"
    )

    # brief.md must have been re-injected into the fresh context.
    assert any('<handoff_artifact name="brief.md">' in c for c in contents), (
        "brief.md must be re-injected after the reset"
    )
    # injected_artifacts should be repopulated by preseed.
    assert "brief.md" in agent.injected_artifacts


@pytest.mark.anyio
async def test_koan_suggest_next_suggestions_appear_on_yield_started(tmp_path):
    """Recorded koan_suggest_next suggestions appear on the yield_started event.

    The loop reads app_state.interactions.next_suggestions at hand-back and
    passes them to yield_started. build_phase_suggestions is the fallback when
    none are recorded (workflow is None here, so fallback = []).
    """
    app_state, agent_state = _make("loop-sugg", str(tmp_path), is_primary=True)
    # Pre-record orchestrator-authored suggestions.
    recorded = [{"id": "plan", "label": "Write plan", "command": "plan", "recommended": True}]
    app_state.interactions.next_suggestions = list(recorded)
    events = []

    async def consume(run_iter):
        async for ev in run_iter:
            events.append(ev)

    with _test_model(call_tools=[]):
        run_iter = _agent(app_state, tmp_path).run(_options("loop-sugg"))
        task = asyncio.create_task(consume(run_iter))

        for _ in range(500):
            if app_state.interactions.yield_future is not None:
                break
            await asyncio.sleep(0.005)
        assert app_state.interactions.yield_future is not None, "loop did not park"

        app_state.run.workflow_done = True
        app_state.interactions.yield_future.set_result(None)
        await asyncio.wait_for(task, timeout=10)

    # next_suggestions consumed and cleared.
    assert app_state.interactions.next_suggestions is None

    # yield_started event carries the recorded suggestions.
    yield_events = [
        e for e in app_state.projection_store.events if e.event_type == "yield_started"
    ]
    assert yield_events, "expected yield_started event"
    payload = yield_events[0].payload
    sugg_ids = [s["id"] for s in payload.get("suggestions", [])]
    assert "plan" in sugg_ids


# -- Mechanical resume sentinel tests -----------------------------------------


def test_yolo_yield_response_phase_derived_when_no_command():
    """_yolo_yield_response synthesizes a phase-derived sentence when command is absent."""
    from koan.agents.loop import _yolo_yield_response

    suggestions = [
        {"id": "plan", "label": "Write plan", "phase": "plan"},
        {"id": "done", "label": "End workflow", "phase": "done"},
    ]
    result = _yolo_yield_response(suggestions)
    assert "plan" in result
    assert "phase" in result.lower()


def test_yolo_yield_response_prefers_command_over_phase():
    """_yolo_yield_response prefers command when both command and phase are present."""
    from koan.agents.loop import _yolo_yield_response

    suggestions = [
        {"id": "custom", "label": "Custom", "command": "do the custom thing", "phase": "plan"},
    ]
    result = _yolo_yield_response(suggestions)
    assert result == "do the custom thing"


@pytest.mark.anyio
async def test_loop_sentinel_resume_no_model_turn_done(tmp_path):
    """When mechanical_resume is set and workflow_done is True, the loop terminates.

    This simulates the done-path: the route sets mechanical_resume and resolves
    yield_future; the loop's sentinel branch sees workflow_done and returns.
    """
    import asyncio
    from koan.agents.base import AgentOptions
    from koan.agents.pydantic_ai import PydanticAIAgent
    from koan.phases import PhaseContext
    from koan.types import ModelSpec
    from unittest.mock import AsyncMock, MagicMock
    # _fake_phase_module_exhausted is defined at module level in this test file.

    app_state = AppState()
    app_state.run.phase = "intake"
    app_state.run.workflow = None

    event_log = AsyncMock()
    event_log.emit_step_transition = AsyncMock()

    agent_state = AgentState(
        agent_id="sentinel-done",
        role="orchestrator",
        subagent_dir=str(tmp_path),
        run_dir="",
        step=0,
        phase_module=_fake_phase_module_exhausted(),
        phase_ctx=PhaseContext(run_dir="", subagent_dir=str(tmp_path)),
        event_log=event_log,
        is_primary=True,
        runner_type="pydantic_ai",
    )
    app_state.agents[agent_state.agent_id] = agent_state

    spec = ModelSpec(provider="google", model="gemini-2.0-flash", thinking="disabled")
    pai_agent = PydanticAIAgent(model_spec=spec, app_state=app_state, subagent_dir=str(tmp_path))
    options = AgentOptions(role="orchestrator", agent_id="sentinel-done", model=None, thinking=None, system_prompt="")

    import koan.agents.adapter as adapter_mod
    from pydantic_ai.models.test import TestModel
    orig_bm, orig_bms = adapter_mod.build_model, adapter_mod.build_model_settings
    adapter_mod.build_model = lambda s, api_key=None, **_: TestModel(call_tools=[], custom_output_text="done")
    adapter_mod.build_model_settings = lambda s: {}

    try:
        async def consume():
            async for _ in pai_agent.run(options):
                pass

        task = asyncio.create_task(consume())

        for _ in range(500):
            if app_state.interactions.yield_future is not None:
                break
            await asyncio.sleep(0.005)
        assert app_state.interactions.yield_future is not None, "loop did not park"

        # Simulate mechanical done: set workflow_done + mechanical_resume, resolve.
        app_state.run.workflow_done = True
        app_state.interactions.mechanical_resume = True
        app_state.interactions.yield_future.set_result(None)

        await asyncio.wait_for(task, timeout=10)
        # Loop terminated cleanly.
        assert task.done()
    finally:
        adapter_mod.build_model = orig_bm
        adapter_mod.build_model_settings = orig_bms


# -- Driver push guard test ---------------------------------------------------


@pytest.mark.anyio
async def test_driver_skips_workflow_completed_when_done(tmp_path):
    """When workflow_done is True, driver_main does not push a second workflow_completed."""
    from unittest.mock import AsyncMock, MagicMock
    from koan.driver import driver_main
    from koan.state import AppState
    from koan.subagent import SubagentResult

    app_state = AppState()
    app_state.run.run_dir = str(tmp_path)
    app_state.run.workflow_done = True  # done path already pushed
    app_state.run.phase = "plan"

    # Patch spawn_subagent to return immediately.
    with patch("koan.driver.spawn_subagent", new_callable=AsyncMock) as mock_spawn:
        mock_spawn.return_value = SubagentResult(exit_code=0, final_response="")
        await driver_main(app_state)

    # No second workflow_completed pushed.
    event_types = [e.event_type for e in app_state.projection_store.events]
    wc_count = event_types.count("workflow_completed")
    assert wc_count == 0, "driver should not push workflow_completed when workflow_done is True"


@pytest.mark.anyio
async def test_driver_pushes_workflow_completed_on_failure(tmp_path):
    """When workflow_done is False (crash), driver pushes workflow_completed then run_cleared."""
    from unittest.mock import AsyncMock
    from koan.driver import driver_main
    from koan.state import AppState
    from koan.subagent import SubagentResult

    app_state = AppState()
    app_state.run.run_dir = str(tmp_path)
    app_state.run.workflow_done = False  # crash exit
    app_state.run.phase = "plan"

    with patch("koan.driver.spawn_subagent", new_callable=AsyncMock) as mock_spawn:
        mock_spawn.return_value = SubagentResult(exit_code=1, final_response="")
        await driver_main(app_state)

    event_types = [e.event_type for e in app_state.projection_store.events]
    assert "workflow_completed" in event_types
    assert "run_cleared" in event_types
    assert event_types.index("workflow_completed") < event_types.index("run_cleared")
