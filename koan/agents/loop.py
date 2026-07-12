# Multi-turn agent loop: run_agent_loop.
#
# Owns the multi-turn conversation lifecycle for the primary orchestrator:
# each turn is one agent.iter() run; a terminal-text turn (End node, no
# outstanding tool calls initiated) is the hand-back signal -- the loop
# parks on a loop-owned yield_future (resolved by api_chat) and resumes
# on the next user message.
#
# Pure yolo/directed helpers are relocated here from mcp_endpoint.py so both
# the loop hand-back and the in-process ask tool can reuse them without
# importing from the web layer.
#
# Steering is injected between graph nodes (after CallToolsNode, before the
# next ModelRequestNode) via agent_run.enqueue(), satisfying the tool-call /
# tool-result adjacency constraint.

from __future__ import annotations

import asyncio
import time
import json
from typing import TYPE_CHECKING, Any, AsyncIterator

if TYPE_CHECKING:
    from ..agents.base import AgentOptions
    from .events import StreamEvent
    from ..state import AgentState, AppState
    from ..tools.koan_tools import ToolDeps
    from ..types import ModelSpec


# -- Pure yolo/directed helpers -----------------------------------------------
# Relocated verbatim from koan/web/mcp_endpoint.py; keeping them here makes
# both the loop hand-back and the in-process koan_ask_question core importable
# without pulling in the web layer.


def _yolo_yield_response(suggestions: list[dict] | None) -> str:
    """Return the auto-response text for a hand-back when running in yolo mode.

    Priority: first recommended non-done suggestion's command
              -> first non-done suggestion's command
              -> first non-done suggestion's phase-derived sentence
              -> "proceed"

    When a suggestion has no command but a non-empty phase (mechanical
    phase-transition suggestions), synthesizes "Proceed to the {phase} phase."
    so yolo stays on the workflow path without hardcoding phase names.


    """
    def _resolve(s: dict) -> str:
        cmd = s.get("command", "")
        if cmd:
            return cmd
        phase = s.get("phase", "")
        if phase:
            return f"Proceed to the {phase} phase."
        return "proceed"
    if not suggestions:
        return "proceed"
    for s in suggestions:
        if s.get("recommended") and s.get("id") != "done":
            return _resolve(s)
    for s in suggestions:
        if s.get("id") != "done":
            return _resolve(s)
    return "proceed"


def _yolo_ask_answer(questions: list[dict]) -> dict:
    """Return a synthetic answer dict for koan_ask_question when running in yolo mode.

    For each question, selects the option marked recommended: true (using its
    label). Falls back to "use your best judgement" when no option is
    recommended, giving the orchestrator latitude to decide.

    Returns a dict matching the shape expected by the existing answer-formatting
    loop: {"answers": [{"answer": "..."}]}.
    """
    answers = []
    for q in questions:
        options = q.get("options") or []
        recommended = next((o for o in options if o.get("recommended")), None)
        if recommended:
            answers.append({"answer": recommended.get("label", recommended.get("value", ""))})
        else:
            answers.append({"answer": "use your best judgement"})
    return {"answers": answers}


def _directed_yolo_response(directed_phases: list[str], current_phase: str) -> str:
    """Build the auto-response text when directed_phases is set.

    Finds current_phase in directed_phases and returns a command that steers
    the orchestrator toward the next phase in the list. Returns "proceed" when
    current_phase is not found or is already the last entry.

    Pure function -- keeps AppState out of the helper, consistent with the
    _yolo_yield_response pattern and easy to unit-test independently.
    """
    try:
        idx = directed_phases.index(current_phase)
    except ValueError:
        return "proceed"
    if idx + 1 >= len(directed_phases):
        return "proceed"
    next_phase = directed_phases[idx + 1]
    if next_phase == "done":
        return 'The workflow is complete. Call koan_set_phase("done") to end.'
    return f"Proceed to the {next_phase} phase."


# -- Steering helper -----------------------------------------------------------


def drain_and_render_steering(
    app_state: AppState,
    agent: AgentState | None,
) -> str | None:
    """Drain the steering queue and render non-empty messages as a plain string.

    Returns a formatted steering-envelope string suitable for
    agent_run.enqueue() injection (pydantic-ai treats a plain string as a
    UserPromptPart). Returns None when there are no messages to inject.

    Uses render_text (text-only path) rather than render_blocks (ContentBlock
    path) because agent_run.enqueue() accepts str, not MCP ContentBlocks.
    """
    from ..agents.steering import drain_for_primary, render_text
    messages = drain_for_primary(app_state, agent)
    if not messages:
        return None
    from ..logger import get_logger
    log = get_logger("loop")
    log.info(
        "steering injected between nodes | agent=%s count=%d",
        agent.agent_id[:8] if agent else "?",
        len(messages),
    )
    # Emit steering_delivered projection event so the dashboard tracks delivery.
    ts_ms_list = [m.timestamp_ms for m in messages]
    delivery_ms = int(time.time() * 1000)
    from ..events import build_steering_delivered
    app_state.projection_store.push_event(
        "steering_delivered",
        build_steering_delivered(len(messages), ts_ms_list, delivery_ms),
    )
    return render_text(messages)


def assemble_resume_prompt(
    messages: list[Any],
    app_state: AppState,
    runner_type: str,
) -> tuple[str, list[dict]]:
    """Build the next-turn prompt + attachment manifest from buffered messages.

    This is the in-process replacement for the koan_yield tool result: when the
    loop resumes after a terminal-text hand-back, the buffered user messages
    become the next prompt. Attachments are delivered as TEXT appended to the
    prompt -- the loop carries a single string, so only the text content of
    upload_ids_to_blocks survives (full binary/image delivery to multimodal
    models is a documented follow-up: it needs multimodal content plumbing on
    the agent.iter prompt and live verification).

    Returns (turn_prompt, manifest) where manifest is the upload audit manifest
    (for the tool_attachments projection event the caller re-emits). Falls back
    to ("proceed", []) when no messages were buffered.
    """
    if not messages:
        return "proceed", []

    from ..phases.format_step import format_user_messages
    from mcp.types import TextContent

    blocks = format_user_messages(messages)
    turn_prompt = "\n\n".join(
        b.text for b in blocks if isinstance(b, TextContent)
    )
    manifest: list[dict] = []
    for msg in messages:
        if msg.attachments and app_state.run.run_dir:
            from ..web.uploads import upload_ids_to_blocks
            attach_blocks, msg_manifest = upload_ids_to_blocks(
                app_state.uploads,
                app_state.run.run_dir,
                msg.attachments,
                runner_type,
            )
            manifest.extend(msg_manifest)
            extra = "\n\n".join(
                b.text for b in attach_blocks if isinstance(b, TextContent)
            )
            if extra:
                turn_prompt = f"{turn_prompt}\n\n{extra}"
    return turn_prompt, manifest


# -- Turn-outcome resolver -----------------------------------------------------


async def resolve_turn_outcome(
    agent_state: "AgentState",
    app_state: "AppState",
) -> "tuple[str, str | None]":
    """Determine what happens after each turn ends (the End node is reached).

    Returns one of three outcomes:
      ("inject", prompt)    -- inject prompt as the next turn's user message;
                               either a new phase's step-1 guidance (step==0)
                               or the next within-phase step's guidance.
      ("handback", None)    -- primary agent, phase steps exhausted; the caller
                               falls through to the yield_started / park / resume
                               hand-back block.
      ("terminate", None)   -- non-primary agent (scout/executor), steps exhausted;
                               the caller returns.

    Position-based rule:
      - step==0 means a koan_set_phase (or koan_set_workflow) this turn reset the
        counter, or we are entering the agent's initial phase. Run the step-0->1
        handshake to deliver the new phase's first step.
      - Otherwise, validate the current step; re-inject it on a non-empty error.
      - If the next step exists, inject its guidance.
      - If no next step remains, hand back (primary) or terminate (non-primary).

    Function-local imports of the step-machine cores avoid a module-level import
    cycle: koan_tools imports from subagent (indirectly via events/state), while
    loop.py is imported by pydantic_ai.py which is imported by subagent.py.
    """
    phase_module = agent_state.phase_module
    ctx = agent_state.phase_ctx

    # Phase-transition case: step==0 means the phase just changed (or initial entry).
    # Run the handshake to deliver the new phase's step-1 guidance.
    if agent_state.step == 0:
        from ..tools.koan_tools import _step_phase_handshake_core
        prompt = await _step_phase_handshake_core(agent_state, app_state)
        return ("inject", prompt)

    # Completion gate: validate the step the agent just finished.
    # A non-empty error re-injects the same step so the agent can correct.
    err = phase_module.validate_step_completion(agent_state.step, ctx)
    if err:
        from ..phases.format_step import format_step
        guidance = phase_module.step_guidance(agent_state.step, ctx)
        return ("inject", f"{err}\n\n{format_step(guidance)}")

    # Advance: ask the phase module for the next step.
    next_step = phase_module.get_next_step(agent_state.step, ctx)
    if next_step is None:
        # Steps exhausted: primary agents hand back to the user; non-primary terminate.
        if agent_state.is_primary:
            return ("handback", None)
        return ("terminate", None)

    # Normal within-phase advancement: inject the next step's guidance.
    from ..tools.koan_tools import _step_within_phase_core
    prompt = await _step_within_phase_core(agent_state, app_state, phase_module, ctx, next_step)
    return ("inject", prompt)


# -- Retry helper -------------------------------------------------------------


def _normalize_tool_args(raw_args: Any) -> dict | None:
    """Normalize ``ToolCallPart.args`` to the ``StreamEvent.tool_args`` contract.

    PydanticAI types ``ToolCallPart.args`` as ``str | dict[str, Any] | None``:
    Anthropic sends a pre-parsed dict at part start, while Ollama/DeepSeek/Gemini
    send a JSON string. ``StreamEvent.tool_args`` is typed ``dict | None``, so we
    enforce that boundary here rather than defensively at each downstream consumer
    (projection fold, subagent fan-out).

    - ``None`` -> ``None`` (preserves the skip behavior in ``build_tool_request``).
    - ``dict`` -> pass-through unchanged.
    - ``str`` -> ``json.loads``; on parse failure fall back to ``{"raw": raw_args}``
      (matches the proven ``koan_reflect`` pattern at projections.py:1531-1535).
    - any other type -> ``{"raw": str(raw_args)}`` (defensive: guards against a
      future PydanticAI variant without a silent type error downstream).
    """
    if raw_args is None:
        return None
    if isinstance(raw_args, dict):
        return raw_args
    if isinstance(raw_args, str):
        try:
            parsed = json.loads(raw_args)
        except (json.JSONDecodeError, TypeError):
            return {"raw": raw_args}
        # A valid JSON string that parses to a non-dict (e.g. a bare list or
        # scalar) still violates the dict contract; wrap it to stay type-safe.
        if isinstance(parsed, dict):
            return parsed
        return {"raw": raw_args}
    return {"raw": str(raw_args)}


async def _stream_model_request_with_retry(
    node: Any,
    agent_run: Any,
    agent_state: "AgentState",
    app_state: "AppState",
) -> "AsyncIterator[Any]":
    """Wrap ModelRequestNode.stream in bounded exponential-backoff retry.

    On a transient provider error (classify_provider_error returns "transient"),
    the helper sleeps compute_backoff_seconds(attempt, cap) and retries up to
    max_retry_attempts times. Retry bounds are read from
    app_state.provider_config.config at retry time (live config, not frozen) so
    a user can adjust them mid-run via "Wait longer" at the escalation prompt.

    On budget exhaustion, an escalation interaction is enqueued via
    enqueue_interaction(agent_state, app_state, "retry_escalation", ...) and
    the helper blocks until the user chooses:
      - "abort"  -> raise AgentError(provider_retry_aborted)
      - "wait"   -> reset the attempt counter and resume retrying with current bounds
      - "proceed_unreviewed" (reviewer role only) -> raise AgentError(reviewer_proceeded_unreviewed)

    Unexpected errors fail fast: re-raised unchanged after emitting a full
    stack trace to the logger.

    Yields pydantic-ai stream events (PartStartEvent / PartDeltaEvent /
    PartEndEvent) so the caller can translate them into StreamEvents as before.
    """
    import asyncio

    from ..logger import get_logger
    from .retry import classify_provider_error, compute_backoff_seconds
    from ..agents.base import AgentDiagnostic, AgentError
    from ..web.interactions import enqueue_interaction

    log = get_logger("loop.retry")

    attempt = 0

    while True:
        try:
            async with node.stream(agent_run.ctx) as stream:
                async for ev in stream:
                    yield ev
            return  # success -- no exception
        except BaseException as err:
            kind = classify_provider_error(err)
            if kind != "transient":
                # Unexpected errors fail fast with a full traceback.
                log.exception(
                    "provider error is not transient -- failing fast | agent=%s err=%r",
                    agent_state.agent_id[:8],
                    err,
                    exc_info=True,
                )
                raise

        # Transient error path.
        attempt += 1
        cfg = app_state.provider_config.config
        max_attempts = cfg.max_retry_attempts
        cap = cfg.max_retry_wait_seconds

        if attempt <= max_attempts:
            wait = compute_backoff_seconds(attempt, cap)
            log.warning(
                "transient provider error on attempt %d/%d -- sleeping %.1fs | agent=%s",
                attempt,
                max_attempts,
                wait,
                agent_state.agent_id[:8],
            )
            await asyncio.sleep(wait)
            continue

        # Budget exhausted -- escalate to the user.
        log.warning(
            "retry budget exhausted after %d attempts -- escalating | agent=%s",
            attempt - 1,
            agent_state.agent_id[:8],
        )

        is_reviewer = (agent_state.role == "reviewer")
        options_list = [
            {"value": "abort", "label": "Abort this agent run"},
            {"value": "wait", "label": "Wait and keep retrying (resets the attempt counter)"},
        ]
        if is_reviewer:
            options_list.append(
                {"value": "proceed_unreviewed", "label": "Proceed without review (skip this review step)"},
            )

        question = {
            "question": (
                f"Provider is unresponsive after {attempt - 1} retry attempts. "
                "What would you like to do?"
            ),
            "options": options_list,
        }

        future = await enqueue_interaction(
            agent_state,
            app_state,
            "retry_escalation",
            {"questions": [question]},
        )
        result = await future
        choice_val = result.get("answers", [{}])[0].get("answer", "abort")

        if choice_val == "wait":
            # Reset attempt counter so the user gets the full budget again.
            attempt = 0
            cfg2 = app_state.provider_config.config
            log.info(
                "user chose wait -- resetting retry counter | agent=%s new_max=%d cap=%.1f",
                agent_state.agent_id[:8],
                cfg2.max_retry_attempts,
                cfg2.max_retry_wait_seconds,
            )
            continue

        if choice_val == "proceed_unreviewed" and is_reviewer:
            raise AgentError(AgentDiagnostic(
                code="reviewer_proceeded_unreviewed",
                agent=agent_state.agent_id,
                stage="stream",
                message="reviewer_proceeded_unreviewed: user chose to proceed without review after retry budget exhausted",
            ))

        # Default: abort.
        raise AgentError(AgentDiagnostic(
            code="provider_retry_aborted",
            agent=agent_state.agent_id,
            stage="stream",
            message=f"provider_retry_aborted: user aborted after {attempt - 1} retry attempts",
        ))


# -- Multi-turn loop -----------------------------------------------------------


async def run_agent_loop(
    pai_agent: Any,
    deps: ToolDeps,
    options: AgentOptions,
    app_state: AppState,
    agent_state: AgentState,
    model_spec: "ModelSpec",
) -> AsyncIterator[StreamEvent]:
    """Drive the multi-turn agent loop, yielding StreamEvents for spawn_subagent.

    Each iteration is one agent.iter() run (one "turn"). The loop uses a
    per-step-turn model: each turn delivers exactly one step's work, and ending
    a turn (the End node) triggers resolve_turn_outcome which determines what
    happens next.

    Bootstrap: before the while loop, _step_phase_handshake_core runs the step
    0->1 handshake for the initial phase. The returned guidance string is the
    first turn's prompt. This replaces the removed boot-directive tool call.

    At each turn end (End node):
      - Mark first_turn_completed (idempotent; the bootstrap-failure signal).
      - If workflow_done (set by koan_set_phase("done")): terminate.
      - Call resolve_turn_outcome(agent_state, app_state):
          "inject"   -> set turn_prompt = payload and continue to the next turn.
          "terminate" -> non-primary agent, steps exhausted; return.
          "handback"  -> primary agent, steps exhausted; fall through to the
                         yield_started / park / resume hand-back block.

    Ending a turn mid-phase advances to the next step (resolver injects it).
    Only step-exhaustion for a primary agent reaches the hand-back.
    The hand-back block sources suggestions from koan_suggest_next if recorded,
    falling back to build_phase_suggestions.

    Mechanical-resume branch: when yield_future resolves with
    mechanical_resume set (a mechanical transition applied via the HTTP
    api_set_phase / api_set_workflow route), the loop skips the model turn
    entirely -- it terminates on "done" or calls resolve_turn_outcome to
    inject the new phase's step-1 guidance (step==0 handshake).

    Steering injection: after each CallToolsNode completes, drain_and_render_steering
    is called. Non-empty result is injected via agent_run.enqueue() which delivers
    it as a UserPromptPart before the next model request -- never between a tool
    call and its result.

    Message history: agent_state.message_history is updated to agent_run.all_messages()
    after each turn, then passed as message_history= to the next agent.iter() call.
    The first turn receives None (empty history) so pydantic-ai treats it fresh.
    At every phase boundary (step==0), _step_phase_handshake_core calls
    reset_phase_context to clear the accumulated history and injection-dedup
    state, so each phase starts with a minimal context. Pre-seeding then
    rebuilds it: preseed_pending_artifacts injects the new phase's immutable
    handovers, preseed_pending_listing injects the artifact listing as its own
    message, and the step guidance is the turn prompt that follows.  On the
    phase-entry turn, apply_artifact_cache_point attaches a long-TTL CachePoint
    to the freshly-preseeded artifact/listing message, which then persists at
    the fixed artifact boundary across subsequent turns via all_messages().

    Cache effectiveness: the loop accumulates input_tokens, cache_read_tokens,
    and request counts across turns and calls check_cache_effectiveness at each
    turn boundary. This is the runtime fail-fast for budget-burning cache misses
    (brief Decision 2): raises AgentError(code="prompt_cache_ineffective") when
    a caching-capable route shows zero cache reads past the warmup threshold.

    Token telemetry: after each turn's cache guard, the loop measures context
    size via Model.count_tokens() on the full message history and emits a
    token_telemetry projection event carrying per-turn usage facts plus the
    measured context size. A single DEBUG-level log line on the "loop" logger
    carries the same data. On count_tokens() failure (any exception) or when
    last_model_request_parameters is None, a warning is logged and the
    projection event is skipped for that turn; the debug log line still fires
    with context_size=-1.

    Args:
        pai_agent: The pydantic-ai Agent instance (already constructed with
                   toolsets, capabilities, and model settings).
        deps: ToolDeps(app_state, agent_state) -- passed to agent.iter(deps=).
        options: AgentOptions carrying system_prompt and role.
        app_state: Live AppState for interaction state and projection events.
        agent_state: AgentState for history, is_primary, and identity.
        model_spec: Resolved ModelSpec carrying provider, model, and caching
                    policy. Used by the cache-effectiveness guard.

    Yields StreamEvents using the same 8-type vocabulary as PydanticAIAgent.run().
    """
    from pydantic_ai._agent_graph import CallToolsNode, End, ModelRequestNode
    from pydantic_ai.messages import (
        FunctionToolResultEvent,
        PartDeltaEvent,
        PartEndEvent,
        PartStartEvent,
        TextPart,
        TextPartDelta,
        ThinkingPart,
        ThinkingPartDelta,
        ToolCallPart,
        ToolCallPartDelta,
    )
    from pydantic_ai.usage import RequestUsage

    from .adapter import build_usage_limits
    from .cache_guard import check_cache_effectiveness
    from .events import StreamEvent

    # Bootstrap: run the step-0->1 handshake to build the first turn's prompt.
    # This sets agent_state.step=1, runs memory injection, and prepends
    # PHASE_ROLE_CONTEXT -- replacing the removed boot-directive tool call.
    # reset_phase_context fires here as a no-op (history and dedup state are
    # empty at bootstrap) so it is safe to seed pending_context_files after
    # this call -- the seed must follow the reset, not precede it.
    from ..tools.koan_tools import _step_phase_handshake_core
    turn_prompt: str = await _step_phase_handshake_core(agent_state, app_state)

    # Seed the project-directory context file (AGENTS.md > CLAUDE.md) so the
    # first model request always carries it, regardless of which tools fire.
    # Seeded here (after the bootstrap handshake) so reset_phase_context's
    # pending_context_files clear -- a no-op at bootstrap -- does not wipe it.
    # Uses options.project_dir (set by spawn_subagent) with a fallback to
    # app_state.run.project_dir; both may be "" in tests (safe -- skipped).
    from ..tools.context_files import discover_context_file
    _project_root = options.project_dir or app_state.run.project_dir
    if _project_root:
        _proj_ctx_file = discover_context_file(_project_root)
        if _proj_ctx_file and _proj_ctx_file not in agent_state.injected_context_files:
            agent_state.pending_context_files.append(_proj_ctx_file)

    # Cumulative cache usage counters -- accumulate across all turns so the
    # guard can detect "never cached anything across the whole run" failures.
    cache_input_total: int = 0
    cache_read_total: int = 0
    cache_requests_total: int = 0
    # Per-agent token telemetry accumulators (debug log line only; cumulative
    # totals for the projection live on Conversation and are folded from the
    # token_telemetry event). Tracked here so the single debug log line can
    # report running totals per turn without recomputing from history.
    cache_write_total: int = 0
    output_total: int = 0

    while True:
        # Pre-seed any queued handover artifacts then the artifact listing into
        # message_history before building the history slice. Artifacts land
        # before the listing (stable order for per-message cache locality).
        # Both are no-ops when their respective pending fields are empty.
        # After pre-seeding, apply_artifact_cache_point attaches the long-TTL
        # cache_artifacts CachePoint to the message the preseeds just appended
        # (identified by index, NOT [-1] which on turns 2+ is the churny tail).
        # It is a no-op on turns where nothing was preseeded (target_index=-1).
        # Function-local import consistent with the loop's existing import pattern.
        from ..tools.handoff_artifacts import (
            apply_artifact_cache_point,
            preseed_pending_artifacts,
            preseed_pending_listing,
        )
        pre_len = len(agent_state.message_history)
        preseed_pending_artifacts(agent_state, app_state)
        preseed_pending_listing(agent_state)
        # Target the last message the preseeds appended THIS turn, or -1 sentinel
        # when nothing was appended (turns 2+) so the CachePoint placed on turn 1
        # rides forward at the fixed artifact boundary via all_messages().
        target_index = len(agent_state.message_history) - 1 if len(agent_state.message_history) > pre_len else -1
        apply_artifact_cache_point(agent_state, target_index)

        # Pass accumulated history so the model has full conversation context.
        # On the first turn, message_history is empty (treated as no history).
        history = agent_state.message_history if agent_state.message_history else None

        run_usage = None
        final_text = ""

        async with pai_agent.iter(
            turn_prompt,
            message_history=history,
            deps=deps,
            usage_limits=build_usage_limits(),
        ) as agent_run:
            async for node in agent_run:

                if isinstance(node, ModelRequestNode):
                    async for ev in _stream_model_request_with_retry(
                        node, agent_run, agent_state, app_state,
                    ):
                        if isinstance(ev, PartStartEvent):
                            part = ev.part
                            if isinstance(part, ToolCallPart):
                                yield StreamEvent(
                                    type="tool_start",
                                    tool_name=part.tool_name,
                                    tool_use_id=part.tool_call_id,
                                    block_index=ev.index,
                                    # Complete args when the provider sends them at
                                    # part start (e.g. Anthropic). Populates command
                                    # fields immediately for these providers.
                                    # Normalize at the StreamEvent boundary so
                                    # downstream consumers always see dict|None
                                    # (Ollama/DeepSeek/Gemini send a JSON str).
                                    tool_args=_normalize_tool_args(part.args),
                                )
                            # Gemini delivers the first text/thinking chunk
                            # inside the PartStartEvent rather than a follow-up
                            # PartDeltaEvent. Emit it now so it is not dropped;
                            # PartDeltaEvents carry the remainder without overlap.
                            elif isinstance(part, TextPart) and part.content:
                                yield StreamEvent(
                                    type="token_delta",
                                    content=part.content,
                                )
                            elif isinstance(part, ThinkingPart) and part.content:
                                yield StreamEvent(
                                    type="thinking",
                                    content=part.content,
                                    is_thinking=True,
                                )
                        elif isinstance(ev, PartDeltaEvent):
                            delta = ev.delta
                            if isinstance(delta, TextPartDelta):
                                yield StreamEvent(
                                    type="token_delta",
                                    content=delta.content_delta,
                                )
                            elif isinstance(delta, ThinkingPartDelta):
                                if delta.content_delta:
                                    yield StreamEvent(
                                        type="thinking",
                                        content=delta.content_delta,
                                        is_thinking=True,
                                    )
                            elif isinstance(delta, ToolCallPartDelta):
                                if delta.args_delta is not None:
                                    args_str = (
                                        delta.args_delta
                                        if isinstance(delta.args_delta, str)
                                        else str(delta.args_delta)
                                    )
                                    yield StreamEvent(
                                        type="tool_input_delta",
                                        content=args_str,
                                        block_index=ev.index,
                                    )
                        elif isinstance(ev, PartEndEvent):
                            part = ev.part
                            if isinstance(part, ToolCallPart):
                                # Emit tool_input_delta BEFORE tool_stop so the
                                # subagent can still look up block_index (tool_stop
                                # pops it from call_ids_by_block).
                                if part.args:
                                    yield StreamEvent(
                                        type="tool_input_delta",
                                        content=None,
                                        tool_args=_normalize_tool_args(part.args),
                                        block_index=ev.index,
                                    )
                                yield StreamEvent(
                                    type="tool_stop",
                                    block_index=ev.index,
                                )
                            if isinstance(part, TextPart) and part.content:
                                # Capture the full assistant text for the hand-back check.
                                final_text = part.content
                                yield StreamEvent(
                                    type="assistant_text",
                                    content=part.content,
                                )

                elif isinstance(node, CallToolsNode):
                    async with node.stream(agent_run.ctx) as events_iter:
                        async for tool_ev in events_iter:
                            if isinstance(tool_ev, FunctionToolResultEvent):
                                result_part = tool_ev.part
                                tool_name = result_part.tool_name
                                tool_use_id = result_part.tool_call_id
                                raw_content = result_part.content
                                content_str = (
                                    raw_content
                                    if isinstance(raw_content, str)
                                    else str(raw_content) if raw_content is not None
                                    else ""
                                )
                                # Read native metrics computed by the tool function
                                # via the AgentState._pending_tool_metrics side
                                # channel, then clear it for the next tool.
                                metrics = getattr(agent_state, '_pending_tool_metrics', None)
                                agent_state._pending_tool_metrics = None
                                yield StreamEvent(
                                    type="tool_result",
                                    tool_name=tool_name,
                                    tool_use_id=tool_use_id,
                                    content=content_str,
                                    metrics=metrics,
                                )

                    # Inject steering after all tools in this node finish, before
                    # the next model request.  This satisfies the adjacency constraint:
                    # the steering message lands at a request boundary, not between a
                    # tool call and its result.
                    steering_text = drain_and_render_steering(app_state, agent_state)
                    if steering_text:
                        agent_run.enqueue(steering_text)

                elif isinstance(node, End):
                    run_usage = agent_run.usage
                    request_usage = RequestUsage(
                        input_tokens=run_usage.input_tokens,
                        output_tokens=run_usage.output_tokens,
                        cache_read_tokens=run_usage.cache_read_tokens,
                        cache_write_tokens=run_usage.cache_write_tokens,
                    )
                    yield StreamEvent(
                        type="turn_complete",
                        usage=request_usage,
                    )

            # Persist the full conversation so the next turn has complete context.
            agent_state.message_history = list(agent_run.all_messages())

        # Accumulate cache usage and run the effectiveness guard.
        # run_usage is None only when no End node was reached (edge case); the
        # is-not-None guard keeps the counters consistent across partial turns.
        if run_usage is not None:
            cache_input_total += run_usage.input_tokens
            cache_read_total += run_usage.cache_read_tokens
            cache_requests_total += run_usage.requests
            cache_write_total += run_usage.cache_write_tokens
            output_total += run_usage.output_tokens
            check_cache_effectiveness(
                provider=model_spec.provider,
                model=model_spec.model,
                caching_mode=model_spec.caching.mode,
                cumulative_input_tokens=cache_input_total,
                cumulative_cache_read_tokens=cache_read_total,
                cumulative_requests=cache_requests_total,
            )

            # -- Per-agent token telemetry: context size + debug log -----------------
            # Measure context size via Model.count_tokens() on the full message
            # history. This is one extra API call per turn -- accepted cost for an
            # accurate context-size reading (run_usage.input_tokens overcounts on
            # tool-call turns and ignores history trimming).
            # Fail-open: on any exception (incl. NotImplementedError from test
            # models), or when last_model_request_parameters is None, log a warning
            # and skip the projection event for this turn. The debug log line still
            # fires with context_size=-1 so the data is never silently lost.
            from ..logger import get_logger

            context_size = -1
            model_params = agent_run.ctx.state.last_model_request_parameters
            if model_params is not None:
                try:
                    count_usage = await pai_agent.model.count_tokens(
                        messages=agent_state.message_history,
                        model_settings=pai_agent.model_settings,
                        model_request_parameters=model_params,
                    )
                    context_size = count_usage.input_tokens
                except Exception:
                    # TestModel/FunctionModel raise NotImplementedError; real
                    # providers may fail transiently. Skip the event, keep the log.
                    get_logger("loop").warning(
                        "token_telemetry: count_tokens() failed for agent=%s model=%s -- skipping event",
                        agent_state.label,
                        model_spec.model,
                    )
            else:
                # End node reached without a model request (shouldn't happen in
                # practice); guard explicitly since count_tokens() requires it.
                get_logger("loop").warning(
                    "token_telemetry: last_model_request_parameters is None for agent=%s -- skipping event",
                    agent_state.label,
                )

            if context_size >= 0:
                from ..events import build_token_telemetry
                app_state.projection_store.push_event(
                    "token_telemetry",
                    build_token_telemetry(
                        input_tokens=run_usage.input_tokens,
                        output_tokens=run_usage.output_tokens,
                        cache_read_tokens=run_usage.cache_read_tokens,
                        cache_write_tokens=run_usage.cache_write_tokens,
                        context_size=context_size,
                    ),
                    agent_id=agent_state.agent_id,
                )

            # Single DEBUG-level log line on the existing "loop" logger so the
            # telemetry is visible without a new logger name (silent by default).
            get_logger("loop").debug(
                "token_telemetry | label=%s provider=%s model=%s context_size=%d "
                "cache_write_total=%d cache_read_total=%d output_total=%d",
                agent_state.label,
                model_spec.provider,
                model_spec.model,
                context_size,
                cache_write_total,
                cache_read_total,
                output_total,
            )

        # Mark first turn completed -- idempotent; the bootstrap-failure signal
        # that replaces the removed first-tool-call handshake.
        agent_state.first_turn_completed = True

        # Termination check: workflow completed via koan_set_phase("done").
        if app_state.run.workflow_done:
            return

        # Invoke the turn-outcome resolver. Ending a turn mid-phase advances
        # to the next step (inject); only step-exhaustion for a primary agent
        # reaches the hand-back; non-primary terminates at exhaustion.
        outcome, payload = await resolve_turn_outcome(agent_state, app_state)

        if outcome == "inject":
            # Next step's guidance ready: re-enter the loop with it as the prompt.
            turn_prompt = payload  # type: ignore[assignment]
            continue

        if outcome == "terminate":
            # Non-primary agent (scout/executor) -- steps exhausted. Return cleanly.
            return

        # outcome == "handback": primary agent, phase steps exhausted.
        # Fall through to the hand-back block below.

        # Primary orchestrator: terminal-text hand-back.
        # Source suggestions from koan_suggest_next if recorded, falling back to
        # the deterministic workflow-derived list. Clear the recorded suggestions
        # after consuming them so stale data cannot bleed into the next hand-back.
        from ..events import build_yield_started
        from ..lib.workflows import build_phase_suggestions
        workflow = app_state.run.workflow
        recorded = app_state.interactions.next_suggestions
        suggestions = (
            recorded if recorded
            else (build_phase_suggestions(workflow, app_state.run.phase) if workflow is not None else [])
        )
        app_state.interactions.next_suggestions = None  # clear after consume

        app_state.projection_store.push_event(
            "yield_started",
            build_yield_started(suggestions),
            agent_id=agent_state.agent_id,
        )

        if app_state.server.yolo:
            # Yolo mode: synthesize the next user message instead of parking.
            # Directed mode steers toward the next phase in the sequence; plain
            # yolo picks from the resolved suggestions so orchestrator-authored
            # commands are honored even in yolo.
            directed = app_state.server.directed_phases
            if directed is not None:
                turn_prompt = _directed_yolo_response(directed, app_state.run.phase)
            else:
                turn_prompt = _yolo_yield_response(suggestions)
        else:
            # Interactive mode: park on yield_future until api_chat resolves it.
            # Reentry guard: if a prior yield is somehow still pending (should not
            # happen in normal flow), skip rather than create a second future.
            existing = app_state.interactions.yield_future
            if existing is not None and not existing.done():
                from ..logger import get_logger
                get_logger("loop").warning(
                    "yield_future already set (reentry) -- loop skipping park",
                )
                return

            loop = asyncio.get_running_loop()
            future = loop.create_future()
            app_state.interactions.yield_future = future
            await future
            app_state.interactions.yield_future = None
            # Mechanical-resume sentinel: a mechanical transition (api_set_phase
            # or api_set_workflow) was applied while parked. apply_set_phase
            # already reset step to 0, so resolve_turn_outcome runs the
            # step-0->1 handshake and injects the new phase's step-1 guidance --
            # no model turn occurs in the old phase. "done" terminates
            # immediately (workflow_done is True).
            if app_state.interactions.mechanical_resume:
                app_state.interactions.mechanical_resume = False
                # Defensive stale-bleed guard: the buffer should be empty (the
                # claim reroutes chat and artifact comments to steering), but
                # if a resolver raced the claim, preserve its messages as
                # steering rather than stranding them for a stale delivery on
                # the NEXT resume.
                if app_state.interactions.user_message_buffer:
                    from ..state import drain_user_messages
                    from ..logger import get_logger
                    get_logger("loop").warning(
                        "mechanical resume: stale user_message_buffer rerouted to steering",
                    )
                    app_state.interactions.steering_queue.extend(
                        drain_user_messages(app_state),
                    )
                if app_state.run.workflow_done:
                    return
                outcome, payload = await resolve_turn_outcome(agent_state, app_state)
                turn_prompt = payload  # type: ignore[assignment]
                continue

            # Drain the user messages that api_chat buffered and form the next prompt.
            from ..state import drain_user_messages
            messages = drain_user_messages(app_state)
            turn_prompt, attach_manifest = assemble_resume_prompt(
                messages, app_state, agent_state.runner_type,
            )
            # Re-emit tool_attachments so the audit log / UI records what the
            # user attached on resume (M7.5 -- the koan_yield handler used to do
            # this; restored here for the in-process hand-back).
            if attach_manifest:
                from ..events import build_tool_attachments
                app_state.projection_store.push_event(
                    "tool_attachments",
                    build_tool_attachments(attach_manifest),
                    agent_id=agent_state.agent_id,
                )
