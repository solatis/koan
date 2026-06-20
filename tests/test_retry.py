# Tests for koan.agents.retry -- pure error classification and backoff.
#
# Layer 1: pure-helper unit tests (no I/O).
# Layer 2: loop-level integration tests using FunctionModel to inject failures.

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest

from koan.agents.retry import classify_provider_error, compute_backoff_seconds


# -- classify_provider_error ---------------------------------------------------


def test_classify_asyncio_timeout():
    assert classify_provider_error(asyncio.TimeoutError()) == "transient"


def test_classify_httpx_timeout():
    import httpx
    assert classify_provider_error(httpx.TimeoutException("timeout")) == "transient"
    assert classify_provider_error(httpx.ConnectTimeout("ct")) == "transient"
    assert classify_provider_error(httpx.ReadTimeout("rt")) == "transient"


def test_classify_httpx_connect_error():
    import httpx
    assert classify_provider_error(httpx.ConnectError("refused")) == "transient"


def test_classify_httpx_remote_protocol_error():
    import httpx
    assert classify_provider_error(httpx.RemoteProtocolError("bad frame")) == "transient"


def test_classify_model_http_error_transient_codes():
    from pydantic_ai.exceptions import ModelHTTPError
    for code in (429, 500, 502, 503, 504, 401, 403):
        err = ModelHTTPError(code, "model")
        assert classify_provider_error(err) == "transient", f"expected transient for {code}"


def test_classify_model_http_error_non_transient_codes():
    from pydantic_ai.exceptions import ModelHTTPError
    for code in (400, 404, 422):
        err = ModelHTTPError(code, "model")
        assert classify_provider_error(err) == "unexpected", f"expected unexpected for {code}"


def test_classify_value_error_is_unexpected():
    assert classify_provider_error(ValueError("bad")) == "unexpected"


def test_classify_runtime_error_is_unexpected():
    assert classify_provider_error(RuntimeError("oops")) == "unexpected"


def test_classify_key_error_is_unexpected():
    assert classify_provider_error(KeyError("k")) == "unexpected"


# -- compute_backoff_seconds ---------------------------------------------------


def test_backoff_attempt_1_doubles_base():
    # attempt=1 -> 1.0 * 2^1 = 2.0
    assert compute_backoff_seconds(1, 60.0) == 2.0


def test_backoff_attempt_2():
    # attempt=2 -> 1.0 * 2^2 = 4.0
    assert compute_backoff_seconds(2, 60.0) == 4.0


def test_backoff_attempt_0():
    # attempt=0 -> 1.0 * 2^0 = 1.0
    assert compute_backoff_seconds(0, 60.0) == 1.0


def test_backoff_capped_at_ceiling():
    # 1.0 * 2^10 = 1024 >> cap of 60
    assert compute_backoff_seconds(10, 60.0) == 60.0


def test_backoff_custom_base():
    # base=2.0, attempt=1 -> 2.0 * 2^1 = 4.0
    assert compute_backoff_seconds(1, 60.0, base=2.0) == 4.0


def test_backoff_cap_less_than_base():
    # cap=0.5, attempt=1 -> min(2.0, 0.5) = 0.5
    assert compute_backoff_seconds(1, 0.5) == 0.5


# -- Loop-level integration tests ---------------------------------------------
# Use FunctionModel to inject failures without hitting real provider endpoints.
# The retry helper reads bounds from app_state.provider_config.config; tests
# set max_retry_attempts=2 and max_retry_wait_seconds=0.001 for fast execution.


from contextlib import contextmanager
from koan.agents.base import AgentOptions
from koan.agents.pydantic_ai import PydanticAIAgent
from koan.config import KoanConfig
from koan.phases import PhaseContext, StepGuidance
from koan.state import AgentState, AppState
from koan.types import ModelSpec


def _fake_phase_module() -> MagicMock:
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


def _make(agent_id: str, tmp_dir: str, *, is_primary: bool = False) -> tuple[AppState, AgentState]:
    app_state = AppState()
    app_state.run.phase = "intake"
    app_state.run.workflow = None
    # Small bounds so tests run fast.
    app_state.provider_config.config = KoanConfig(
        max_retry_attempts=2,
        max_retry_wait_seconds=0.001,
    )
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
def _function_model(stream_func):
    """Patch the adapter so the agent runs against a FunctionModel with the given stream_func."""
    from pydantic_ai.models.function import FunctionModel
    import koan.agents.adapter as adapter_mod
    orig_bm, orig_bms = adapter_mod.build_model, adapter_mod.build_model_settings
    adapter_mod.build_model = lambda s, api_key=None, **_: FunctionModel(stream_function=stream_func)
    adapter_mod.build_model_settings = lambda s: {}
    try:
        yield
    finally:
        adapter_mod.build_model = orig_bm
        adapter_mod.build_model_settings = orig_bms


def _agent(app_state: AppState, tmp_path) -> PydanticAIAgent:
    spec = ModelSpec(provider="google", model="gemini-2.0-flash", thinking="disabled")
    return PydanticAIAgent(model_spec=spec, app_state=app_state, subagent_dir=str(tmp_path))


def _options(agent_id: str) -> AgentOptions:
    return AgentOptions(
        role="orchestrator", agent_id=agent_id, model=None, thinking=None,
        system_prompt="",
    )


@pytest.mark.anyio
async def test_transient_error_retried_then_succeeds(tmp_path):
    """A stream that fails once with ConnectError then succeeds completes normally."""
    import httpx

    call_count = 0

    async def flaky_stream(messages, info):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise httpx.ConnectError("transient connect failure")
        yield "done"

    app_state, _ = _make("retry-succeed", str(tmp_path))

    with _function_model(flaky_stream):
        events = [ev async for ev in _agent(app_state, tmp_path).run(_options("retry-succeed"))]

    # Should have completed successfully (turn_complete event present).
    assert any(e.type == "turn_complete" for e in events), "expected turn_complete"
    # Model was called twice (1 failure + 1 success).
    assert call_count == 2


@pytest.mark.anyio
async def test_unexpected_error_fails_fast(tmp_path):
    """An unexpected (non-transient) error propagates without retrying."""
    call_count = 0

    async def bad_stream(messages, info):
        nonlocal call_count
        call_count += 1
        raise RuntimeError("unexpected internal error")
        yield  # make it an async generator

    app_state, _ = _make("retry-fast-fail", str(tmp_path))

    with _function_model(bad_stream):
        with pytest.raises(RuntimeError, match="unexpected internal error"):
            _ = [ev async for ev in _agent(app_state, tmp_path).run(_options("retry-fast-fail"))]

    # Model called exactly once (no retries for unexpected).
    assert call_count == 1


@pytest.mark.anyio
async def test_budget_exhausted_abort_raises_agent_error(tmp_path):
    """When retry budget is exhausted and the user chooses abort, AgentError is raised."""
    import httpx
    from koan.agents.base import AgentError

    async def always_fail(messages, info):
        raise httpx.ConnectError("always fails")
        yield  # make it an async generator

    app_state, _ = _make("retry-abort", str(tmp_path))

    events = []

    async def consume(run_iter):
        async for ev in run_iter:
            events.append(ev)

    with _function_model(always_fail):
        run_iter = _agent(app_state, tmp_path).run(_options("retry-abort"))
        task = asyncio.create_task(consume(run_iter))

        # Wait for the escalation interaction to be enqueued.
        for _ in range(500):
            active = app_state.interactions.active_interaction
            if active is not None and active.type == "retry_escalation":
                break
            await asyncio.sleep(0.005)

        active = app_state.interactions.active_interaction
        assert active is not None and active.type == "retry_escalation", (
            "expected retry_escalation interaction to be enqueued"
        )

        # Assert questions_asked event was emitted.
        assert any(
            e.event_type == "questions_asked" for e in app_state.projection_store.events
        ), "expected questions_asked event"

        # User chooses abort.
        active.future.set_result({"answers": [{"answer": "abort"}]})

        with pytest.raises(AgentError) as exc_info:
            await asyncio.wait_for(task, timeout=10)

    assert exc_info.value.diagnostic.code == "provider_retry_aborted"


@pytest.mark.anyio
async def test_budget_exhausted_wait_resets_counter_and_retries(tmp_path):
    """When the user chooses wait, the attempt counter resets and retrying resumes."""
    import httpx

    call_count = 0
    escalation_count = 0

    async def fail_then_succeed(messages, info):
        nonlocal call_count
        call_count += 1
        # Fail until we've escalated once (user chose wait, then succeed on next call).
        if call_count <= 3:
            raise httpx.ConnectError("fail")
        yield "done"

    app_state, _ = _make("retry-wait", str(tmp_path))
    # Only 2 attempts before escalation; after user chooses wait the counter resets.
    app_state.provider_config.config = KoanConfig(
        max_retry_attempts=2,
        max_retry_wait_seconds=0.001,
    )

    events = []

    async def consume(run_iter):
        async for ev in run_iter:
            events.append(ev)

    with _function_model(fail_then_succeed):
        run_iter = _agent(app_state, tmp_path).run(_options("retry-wait"))
        task = asyncio.create_task(consume(run_iter))

        # Wait for first escalation.
        for _ in range(500):
            active = app_state.interactions.active_interaction
            if active is not None and active.type == "retry_escalation":
                break
            await asyncio.sleep(0.005)

        active = app_state.interactions.active_interaction
        assert active is not None

        # User chooses wait: this resets the attempt counter.
        escalation_count += 1
        active.future.set_result({"answers": [{"answer": "wait"}]})

        # The loop retries again and should eventually succeed (call_count > 3).
        await asyncio.wait_for(task, timeout=10)

    assert any(e.type == "turn_complete" for e in events), "expected turn_complete after wait+retry"
    assert call_count > 3, "expected more than 3 calls (post-wait retries happened)"


@pytest.mark.anyio
async def test_budget_exhausted_reviewer_proceed_unreviewed(tmp_path):
    """A reviewer-role agent offered proceed_unreviewed raises reviewer_proceeded_unreviewed."""
    import httpx
    from koan.agents.base import AgentError

    async def always_fail(messages, info):
        raise httpx.ConnectError("fails")
        yield  # async generator

    app_state, agent_state = _make("retry-reviewer", str(tmp_path))
    agent_state.role = "reviewer"

    events = []

    async def consume(run_iter):
        async for ev in run_iter:
            events.append(ev)

    with _function_model(always_fail):
        run_iter = _agent(app_state, tmp_path).run(_options("retry-reviewer"))
        task = asyncio.create_task(consume(run_iter))

        # Wait for escalation.
        for _ in range(500):
            active = app_state.interactions.active_interaction
            if active is not None and active.type == "retry_escalation":
                break
            await asyncio.sleep(0.005)

        active = app_state.interactions.active_interaction
        assert active is not None

        # Verify proceed_unreviewed option is present (only for reviewer role).
        questions = active.payload.get("questions", [])
        assert questions, "expected at least one question in escalation"
        option_values = [o["value"] for o in questions[0]["options"]]
        assert "proceed_unreviewed" in option_values, (
            "reviewer role must include proceed_unreviewed option"
        )

        # User chooses proceed_unreviewed.
        active.future.set_result({"answers": [{"answer": "proceed_unreviewed"}]})

        with pytest.raises(AgentError) as exc_info:
            await asyncio.wait_for(task, timeout=10)

    assert exc_info.value.diagnostic.code == "reviewer_proceeded_unreviewed"
