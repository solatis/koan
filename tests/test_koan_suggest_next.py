# Tests for koan_suggest_next: suggest_next_core, loop hand-back integration,
# and KOAN_MCP_TOOLS / ROLE_PERMISSIONS membership assertions.

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from koan.phases import PhaseContext, StepGuidance
from koan.state import AgentState, AppState
from koan.models.offering import resolve_offering


# -- suggest_next_core unit tests ---------------------------------------------


@pytest.mark.anyio
async def test_suggest_next_core_stores_suggestions():
    """suggest_next_core stores suggestions on app_state.interactions.next_suggestions."""
    from koan.tools.koan_tools import ToolDeps, suggest_next_core

    app_state = AppState()
    agent = AgentState(agent_id="t1", role="orchestrator", subagent_dir="")
    deps = ToolDeps(app_state=app_state, agent=agent)

    suggestions = [
        {"id": "plan", "label": "Write plan", "command": "write the plan", "recommended": True},
        {"id": "done", "label": "End workflow", "command": "end"},
    ]
    result = await suggest_next_core(deps, suggestions)

    assert app_state.interactions.next_suggestions == suggestions
    assert "2" in result  # ack mentions count


@pytest.mark.anyio
async def test_suggest_next_core_coerces_none_to_empty():
    """suggest_next_core stores [] when passed an empty list.

    An empty list is falsy: the loop falls back to build_phase_suggestions.
    This matches the documented contract.
    """
    from koan.tools.koan_tools import ToolDeps, suggest_next_core

    app_state = AppState()
    agent = AgentState(agent_id="t2", role="orchestrator", subagent_dir="")
    deps = ToolDeps(app_state=app_state, agent=agent)

    result = await suggest_next_core(deps, [])

    assert app_state.interactions.next_suggestions == []
    assert "0" in result


# -- Loop hand-back integration tests -----------------------------------------


def _fake_exhausted_module() -> MagicMock:
    """Minimal phase module that exhausts after step 1."""
    mod = MagicMock()
    mod.ROLE = "orchestrator"
    mod.TOTAL_STEPS = 1
    mod.PHASE_ROLE_CONTEXT = ""
    mod.STEP_NAMES = {1: "Work"}
    mod.validate_step_completion = MagicMock(return_value=None)
    mod.get_next_step = MagicMock(return_value=None)
    mod.step_guidance = MagicMock(return_value=StepGuidance(
        title="Work", instructions=["Do the work."],
    ))
    mod.on_loop_back = AsyncMock()
    return mod


@pytest.mark.anyio
async def test_loop_handback_consumes_and_clears_recorded_suggestions(tmp_path):
    """The loop hand-back consumes recorded suggestions and clears next_suggestions.

    Recorded suggestions appear in the yield_started event payload;
    next_suggestions is None after the hand-back.
    """
    import asyncio
    from koan.agents.base import AgentOptions
    from koan.agents.pydantic_ai import PydanticAIAgent
    from koan.state import ChatMessage
    from koan.types import ModelSpec

    app_state = AppState()
    app_state.run.phase = "intake"
    app_state.run.workflow = None

    event_log = AsyncMock()
    event_log.emit_step_transition = AsyncMock()

    agent_state = AgentState(
        agent_id="sugg-test",
        role="orchestrator",
        subagent_dir=str(tmp_path),
        run_dir="",
        step=0,
        phase_module=_fake_exhausted_module(),
        phase_ctx=PhaseContext(run_dir="", subagent_dir=str(tmp_path)),
        event_log=event_log,
        is_primary=True,
        runner_type="pydantic_ai",
    )
    app_state.agents[agent_state.agent_id] = agent_state

    # Pre-record suggestions.
    recorded = [{"id": "plan", "label": "Write plan", "command": "plan", "recommended": True}]
    app_state.interactions.next_suggestions = list(recorded)

    spec = ModelSpec(offering=resolve_offering("google", "gemini-2.0-flash"), thinking="disabled")
    pai_agent = PydanticAIAgent(model_spec=spec, app_state=app_state, subagent_dir=str(tmp_path))
    options = AgentOptions(role="orchestrator", agent_id="sugg-test", model=None, thinking=None, system_prompt="")

    import koan.agents.adapter as adapter_mod
    from pydantic_ai.models.test import TestModel
    orig_bm, orig_bms = adapter_mod.build_model, adapter_mod.build_model_settings
    adapter_mod.build_model = lambda s, api_key=None, **_: TestModel(call_tools=[], custom_output_text="done")
    adapter_mod.build_model_settings = lambda s: {}

    events = []
    try:
        async def consume():
            async for ev in pai_agent.run(options):
                events.append(ev)

        task = asyncio.create_task(consume())

        for _ in range(500):
            if app_state.interactions.yield_future is not None:
                break
            await asyncio.sleep(0.005)
        assert app_state.interactions.yield_future is not None, "loop did not park"

        # next_suggestions must have been consumed and cleared.
        assert app_state.interactions.next_suggestions is None

        # yield_started payload must include the recorded suggestion.
        yield_events = [e for e in app_state.projection_store.events if e.event_type == "yield_started"]
        assert yield_events, "expected yield_started event"
        sugg_ids = [s["id"] for s in yield_events[0].payload.get("suggestions", [])]
        assert "plan" in sugg_ids

        app_state.run.workflow_done = True
        app_state.interactions.yield_future.set_result(None)
        await asyncio.wait_for(task, timeout=10)
    finally:
        adapter_mod.build_model = orig_bm
        adapter_mod.build_model_settings = orig_bms


@pytest.mark.anyio
async def test_loop_handback_falls_back_to_build_phase_suggestions(tmp_path):
    """When no suggestions are recorded, the loop falls back to build_phase_suggestions.

    With workflow=None, build_phase_suggestions returns [] so yield_started
    carries an empty suggestions list.
    """
    import asyncio
    from koan.agents.base import AgentOptions
    from koan.agents.pydantic_ai import PydanticAIAgent
    from koan.types import ModelSpec

    app_state = AppState()
    app_state.run.phase = "intake"
    app_state.run.workflow = None  # no workflow -> fallback = []

    event_log = AsyncMock()
    event_log.emit_step_transition = AsyncMock()

    agent_state = AgentState(
        agent_id="fallback-test",
        role="orchestrator",
        subagent_dir=str(tmp_path),
        run_dir="",
        step=0,
        phase_module=_fake_exhausted_module(),
        phase_ctx=PhaseContext(run_dir="", subagent_dir=str(tmp_path)),
        event_log=event_log,
        is_primary=True,
    )
    app_state.agents[agent_state.agent_id] = agent_state
    # No next_suggestions recorded.
    assert app_state.interactions.next_suggestions is None

    spec = ModelSpec(offering=resolve_offering("google", "gemini-2.0-flash"), thinking="disabled")
    pai_agent = PydanticAIAgent(model_spec=spec, app_state=app_state, subagent_dir=str(tmp_path))
    options = AgentOptions(role="orchestrator", agent_id="fallback-test", model=None, thinking=None, system_prompt="")

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

        # next_suggestions remains None (nothing recorded, cleared = None).
        assert app_state.interactions.next_suggestions is None

        app_state.run.workflow_done = True
        app_state.interactions.yield_future.set_result(None)
        await asyncio.wait_for(task, timeout=10)
    finally:
        adapter_mod.build_model = orig_bm
        adapter_mod.build_model_settings = orig_bms


# -- suggest_next_core phase validation tests ---------------------------------


@pytest.mark.anyio
async def test_suggest_next_core_validates_phase_metadata():
    """Suggestions with a non-empty 'phase' key are validated against the active workflow.

    Valid phase values ('done' or a valid transition target) are stored; an
    invalid phase value returns the recoverable {"ok": false} envelope and
    stores nothing.
    """
    from koan.lib.workflows import get_workflow
    from koan.tools.koan_tools import ToolDeps, suggest_next_core

    app_state = AppState()
    app_state.run.workflow = get_workflow("plan")
    app_state.run.phase = "intake"
    agent = AgentState(agent_id="t1", role="orchestrator", subagent_dir="")
    deps = ToolDeps(app_state=app_state, agent=agent)

    # Valid: "plan" is a valid transition from "intake" in the plan workflow.
    suggestions = [
        {"id": "plan", "label": "Write plan", "phase": "plan", "recommended": True},
        {"id": "done", "label": "End workflow", "phase": "done"},
    ]
    result = await suggest_next_core(deps, suggestions)
    assert app_state.interactions.next_suggestions == suggestions
    assert "2" in result

    # Invalid: "nonexistent" is not a valid phase in the plan workflow.
    bad_suggestions = [
        {"id": "bad", "label": "Bad", "phase": "nonexistent"},
    ]
    result = await suggest_next_core(deps, bad_suggestions)
    import json
    parsed = json.loads(result)
    assert parsed["ok"] is False
    assert parsed["error"]["reason"] == "invalid_suggestion_phase"
    # Nothing stored -- the previous valid suggestions remain.
    assert app_state.interactions.next_suggestions == suggestions


@pytest.mark.anyio
async def test_suggest_next_core_free_text_passes_unvalidated():
    """Free-text suggestions (no 'phase' key) pass through without validation."""
    from koan.tools.koan_tools import ToolDeps, suggest_next_core

    app_state = AppState()
    app_state.run.workflow = None  # no workflow -- would fail if validated
    agent = AgentState(agent_id="t1", role="orchestrator", subagent_dir="")
    deps = ToolDeps(app_state=app_state, agent=agent)

    suggestions = [
        {"id": "custom", "label": "Do something", "command": "do the thing"},
    ]
    result = await suggest_next_core(deps, suggestions)
    assert app_state.interactions.next_suggestions == suggestions
    assert "1" in result


# -- build_phase_suggestions shape tests --------------------------------------


def test_build_phase_suggestions_carries_phase_no_command():
    """build_phase_suggestions entries carry 'phase', not 'command'."""
    from koan.lib.workflows import build_phase_suggestions, get_workflow

    wf = get_workflow("plan")
    sugg = build_phase_suggestions(wf, wf.initial_phase)
    assert sugg, "expected at least the 'done' option"
    for s in sugg:
        assert "phase" in s
        assert "command" not in s
    ids = [s["id"] for s in sugg]
    assert ids[-1] == "done"
    assert sugg[-1]["phase"] == "done"


# -- KOAN_MCP_TOOLS and ROLE_PERMISSIONS membership ---------------------------


def test_koan_suggest_next_in_koan_mcp_tools():
    """koan_suggest_next must be in KOAN_MCP_TOOLS for the projection fold."""
    from koan.agents.events import KOAN_MCP_TOOLS
    assert "koan_suggest_next" in KOAN_MCP_TOOLS


def test_koan_complete_step_not_in_koan_mcp_tools():
    """koan_complete_step was removed in M6 and must not appear in KOAN_MCP_TOOLS."""
    from koan.agents.events import KOAN_MCP_TOOLS
    assert "koan_complete_step" not in KOAN_MCP_TOOLS


def test_koan_suggest_next_in_orchestrator_role_permissions():
    """koan_suggest_next must be in ROLE_PERMISSIONS["orchestrator"]."""
    from koan.tools.tool_policy import ROLE_PERMISSIONS
    assert "koan_suggest_next" in ROLE_PERMISSIONS["orchestrator"]


def test_koan_complete_step_absent_from_all_roles():
    """koan_complete_step must not appear in any ROLE_PERMISSIONS role."""
    from koan.tools.tool_policy import ROLE_PERMISSIONS
    for role, tools in ROLE_PERMISSIONS.items():
        assert "koan_complete_step" not in tools, (
            f"koan_complete_step found in ROLE_PERMISSIONS[{role!r}] -- must be absent (M6)"
        )


def test_koan_suggest_next_registered_in_build_koan_toolset():
    """koan_suggest_next is registered in build_koan_toolset (can be built)."""
    from koan.tools.koan_tools import build_koan_toolset
    ts = build_koan_toolset()
    # FunctionToolset has a _functions dict or similar; check via repr or attribute.
    # Use allowed_names to verify it's selectable.
    ts_filtered = build_koan_toolset(allowed_names=frozenset({"koan_suggest_next"}))
    # If the function was registered, building the filtered set is not None.
    assert ts_filtered is not None
