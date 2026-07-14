# PydanticAIAgent: in-process agent implementing the existing Agent protocol.
#
# Drives one pydantic-ai agent.iter() run on a provider model (Gemini in M2,
# all four providers in M7) and translates the streamed graph events into koan's
# 9-type StreamEvent vocabulary. The translation layer is the
# highest-risk seam in the migration -- see the StreamEvent fidelity constraint
# in brief.md.
#
# M2 scope: one agent.iter() run (one turn), consumed by spawn_subagent's
# existing single run() iteration. Multi-turn loop / run_agent_loop lands in M5.
# The Agent protocol's subprocess-shaped members (register_process, exit_code,
# stderr_output, list_models) are no-ops pending the M6 protocol slim.
#
# node/event -> StreamEvent translation map (verified against pydantic-ai 2.0.0b6):
#
#  ModelRequestNode stream events:
#    PartStartEvent(TextPart)         -> token_delta if part.content (Gemini ships
#                                        first chunk here; PartDeltaEvents carry rest)
#    PartDeltaEvent(TextPartDelta)    -> token_delta  (content_delta)
#    PartEndEvent(TextPart)           -> assistant_text (full accumulated text)
#    PartStartEvent(ThinkingPart)     -> thinking if part.content (leading chunk)
#    PartDeltaEvent(ThinkingPartDelta)-> thinking (content_delta)
#    PartEndEvent(ThinkingPart)       -> (no explicit event; flush already done)
#    PartStartEvent(ToolCallPart)     -> tool_start (tool_name, tool_use_id,
#                                                    block_index=part.index)
#    PartDeltaEvent(ToolCallPartDelta)-> tool_input_delta (args_delta, block_index)
#    PartEndEvent(ToolCallPart)       -> tool_stop (block_index)
#    FinalResultEvent                 -> (no event; End node signals turn_complete)
#
#  CallToolsNode stream events:
#    FunctionToolCallEvent            -> (already emitted via PartStartEvent above)
#    FunctionToolResultEvent          -> tool_result (tool_name, tool_use_id,
#                                                     content, metrics for read)
#      .part is RetryPromptPart       -> tool_failed (tool_name, tool_use_id,
#                                        content = human-readable validation error;
#                                        the tool body never ran)
#
#  End node                           -> turn_complete (with RunUsage on usage field)
#
# tool_use_id = ToolCallPart.tool_call_id so spawn_subagent's call_id_by_tool_use_id
# correlation works unchanged.

from __future__ import annotations

import uuid
from typing import Any, AsyncIterator

from .base import AgentDiagnostic, AgentError, AgentOptions
from .events import StreamEvent
from ..logger import get_logger
from ..types import ModelSpec

log = get_logger("pydantic_ai")


class PydanticAIAgent:
    """In-process agent that drives pydantic-ai's agent.iter() and emits StreamEvents.

    Implements the existing Agent protocol (register_process / exit_code /
    stderr_output as no-ops -- the M6 protocol slim drops these). Covers Gemini
    in M2; Anthropic/OpenAI/Bedrock land in M7 via the provider adapter.
    """

    name: str = "pydantic_ai"

    def __init__(
        self,
        model_spec: ModelSpec,
        app_state: Any,
        subagent_dir: str,
    ) -> None:
        """Construct a PydanticAIAgent from a resolved ModelSpec.

        Args:
            model_spec: Resolved provider + model + settings (from AgentRegistry).
            app_state: Live AppState; passed through to ToolDeps so in-process
                       tools can read/mutate driver state.
            subagent_dir: The subagent's working directory (task.json location).
                          Stored for audit/debug use; not used for path resolution.
        """
        self._model_spec = model_spec
        self._app_state = app_state
        self._subagent_dir = subagent_dir
        # Populated during run(); used by exit_code and stderr_output properties.
        self._success: bool = False
        self._failure_message: str = ""

    # -- Agent protocol no-ops (subprocess-shaped members) --------------------
    # These members describe a subprocess the in-process agent does not have.
    # They remain as no-ops until M6 slims the Agent protocol to remove them.

    def register_process(self, registry: dict, agent_id: str) -> None:
        """No-op: no subprocess to register.

        PydanticAIAgent runs in-process; there is no OS process handle to
        insert into the active-process registry. The M6 protocol slim drops
        this member entirely along with _active_processes.
        """

    @property
    def exit_code(self) -> int | None:
        """Return 0 on success, 1 on captured failure, None before run() completes.

        Mirrors the subprocess exit-code convention used by spawn_subagent's
        error-path logic. Populated after run() finishes its iteration.
        """
        if not self._success and self._failure_message:
            return 1
        if self._success:
            return 0
        return None

    @property
    def stderr_output(self) -> str:
        """Return empty string (no subprocess stderr stream).

        PydanticAIAgent captures errors via exception handling in run(); there
        is no separate stderr channel. spawn_subagent uses this as the fallback
        for error_str when exit_code != 0 and final_response is empty.
        """
        return self._failure_message

    async def interrupt(self) -> None:
        """Cancel the iter task (not yet implemented in M2; lands in M5/M7).

        M5 wires the loop-owned task handle so interrupt() can cancel it with
        the partial history intact. Until then, callers expecting to interrupt
        mid-turn must use the existing process-kill path (which is a no-op here).
        """
        raise NotImplementedError("interrupt() not yet implemented; lands in M5")

    async def compact(self) -> None:
        """Trigger context compaction (unimplemented; deferred to M7 advanced control)."""
        raise NotImplementedError("compact() not yet implemented; deferred to M7")

    @classmethod
    def list_models(cls, installation: Any) -> list:
        """Return empty list (model listing moves to the provider adapter in M8).

        The probe-time list_models path is replaced by the provider adapter's
        static model registry in M8. Until then, return an empty list so callers
        that iterate over it see no results without failing.
        """
        return []

    # -- Core run() implementation --------------------------------------------

    async def run(self, options: AgentOptions) -> AsyncIterator[StreamEvent]:
        """Drive one agent.iter() run and yield StreamEvents for spawn_subagent.

        Credentials and connection settings are resolved from the per-run frozen
        config snapshot (app_state.run.frozen_config / frozen_credential_store),
        not live global config, so the run is immune to mid-run settings changes.

        Translates pydantic-ai's graph-node / stream events into koan's 9-type
        StreamEvent vocabulary so spawn_subagent's existing fan-out is unchanged.
        M2 scope: one turn (one agent.iter() run). Multi-turn loop lands in M5.

        The translation follows the map in this module's header comment; key
        invariants:
        - tool_start / tool_input_delta / tool_stop carry block_index matching
          the PartStartEvent.index so spawn_subagent's call_ids_by_block map works.
        - tool_result carries tool_use_id matching the ToolCallPart.tool_call_id
          so call_id_by_tool_use_id correlation works.
        - turn_complete carries usage (RequestUsage) from run.usage so
          spawn_subagent can emit real input_tokens/output_tokens at agent_exited.

        Raises AgentError on unrecoverable model or tool failures so spawn_subagent
        can emit a structured agent_spawn_failed projection event.

        M3 toolset composition: the registered koan toolset is composed per role
        via compose_toolset(build_tool_policy(), ...), building a static
        phase-independent vocabulary so the tool-definition cache prefix stays
        byte-stable across all phases.  Phase-appropriateness for the
        orchestrator's phase-conditional tools (koan_request_scouts,
        koan_request_executor) is enforced at call time by phase_gate_message.

        M4 context-file injection: the project-directory context file
        (AGENTS.md > CLAUDE.md) is seeded into pending_context_files at loop
        start and injected before the first model request via a ProcessHistory
        capability. Subsequent subtree files are queued just-in-time by the
        path-bearing tools and injected before the next request.

        Native metrics are computed by the tool functions themselves and stored
        on AgentState._pending_tool_metrics; the loop reads and clears this field
        after each tool completes (replacing the former text-output parsing).
        """
        from pydantic_ai._agent_graph import CallToolsNode, End, ModelRequestNode
        from pydantic_ai.agent import Agent as PAIAgent
        from pydantic_ai.messages import (
            FunctionToolResultEvent,
            PartDeltaEvent,
            PartEndEvent,
            PartStartEvent,
            TextPartDelta,
            ThinkingPartDelta,
            ToolCallPart,
            ToolCallPartDelta,
        )
        from pydantic_ai.usage import RequestUsage

        from ..tools.builtin_tools import build_builtin_toolset
        from ..tools.koan_tools import ToolDeps, build_koan_toolset
        from ..tools.tool_policy import build_tool_policy, compose_toolset

        # Import the adapter module (not individual names) so monkeypatching
        # adapter_mod.build_model in tests is visible at call time.  A
        # 'from .adapter import build_model' would bind the name too early and
        # defeat the patch.
        import koan.agents.adapter as _adapter_mod

        # api_key is baked into the ModelSpec at flatten time (resolve_model_spec),
        # so the spawn path reads it directly from the spec -- no credential store
        # lookup is needed here. base_url and region are also inlined at flatten time.
        api_key = self._model_spec.api_key

        # Build the provider model and settings from the resolved ModelSpec.
        try:
            model = _adapter_mod.build_model(
                self._model_spec,
                api_key,
                region=None,
                base_url=self._model_spec.base_url,
            )
            model_settings = _adapter_mod.build_model_settings(self._model_spec)
        except Exception as e:
            raise AgentError(AgentDiagnostic(
                code="model_build_failed",
                agent=self.name,
                stage="spawn",
                message=f"Failed to build model for {self._model_spec.provider}: {e}",
            ))

        # Resolve the AgentState for this run from app_state.agents.
        # spawn_subagent registers it before calling run(), so it must be present.
        agent_state = self._app_state.agents.get(options.agent_id)
        if agent_state is None:
            raise AgentError(AgentDiagnostic(
                code="agent_not_registered",
                agent=self.name,
                stage="spawn",
                message=f"AgentState for agent_id={options.agent_id!r} not in app_state.agents",
            ))

        # ToolDeps closes over app_state and this agent's AgentState.
        deps = ToolDeps(app_state=self._app_state, agent=agent_state)

        # Build the history processor that drains pending_context_files before
        # each model request and injects them as <project_instructions> user
        # messages. ProcessHistory is the v2.0.0b6 replacement for the
        # deprecated history_processors kwarg; it calls before_model_request.
        from ..tools.context_files import make_context_history_processor
        from pydantic_ai.capabilities.process_history import ProcessHistory
        context_processor = make_context_history_processor(deps)
        capabilities = [ProcessHistory(context_processor)]

        # Compose toolsets per role -- M3 fence replacement, updated for
        # prompt-cache stability.  Phase-appropriateness for the orchestrator's
        # phase-conditional tools (koan_request_scouts, koan_request_executor)
        # is enforced at call time by phase_gate_message rather than here, so the
        # tool-definition prefix stays byte-stable across all phases.
        policy = build_tool_policy()
        allowed = compose_toolset(policy, options.role)
        koan_toolset = build_koan_toolset(allowed_names=allowed)
        builtin_toolset = build_builtin_toolset()

        # The builtin (untrusted) toolset is wrapped in a byte ceiling: no
        # result above TOOL_RESULT_CEILING_BYTES ever enters message history,
        # regardless of per-tool bounds (docs/tool-output-limits.md). The
        # koan toolset stays unwrapped -- trusted tools are bound by
        # construction. WrapperToolset delegates get_tools/get_instructions,
        # so tool schemas and the cache-stable prefix are untouched.
        from ..tools.byte_budget import ByteBudgetToolset

        # Construct pydantic-ai Agent with instructions (v2 prefers instructions
        # over system_prompt for the byte-stable cache prefix).
        pai_agent: PAIAgent[ToolDeps, str] = PAIAgent(
            model=model,
            instructions=options.system_prompt,
            toolsets=[koan_toolset, ByteBudgetToolset(wrapped=builtin_toolset)],
            model_settings=model_settings,
            capabilities=capabilities,
        )

        # Per-request usage accumulator for the turn_complete event.
        # RunUsage aggregates across all model requests in the run.
        run_usage = None

        try:
            # Delegate the iteration to the driver-owned multi-turn loop. For a
            # primary orchestrator this runs many turns -- parking on yield_future
            # at each terminal-text hand-back and resuming on the next user message
            # -- and returns only when koan_set_phase("done") sets workflow_done.
            # Scouts/executors (is_primary=False) run exactly one turn and return.
            # run_agent_loop owns agent_state.message_history across turns and emits
            # the same 9-type StreamEvent vocabulary documented above.
            from .loop import run_agent_loop
            async for ev in run_agent_loop(
                pai_agent, deps, options, self._app_state, agent_state, self._model_spec,
            ):
                yield ev

            self._success = True

        except AgentError:
            self._failure_message = "agent error during run"
            raise
        except Exception as e:
            self._failure_message = str(e)
            raise AgentError(AgentDiagnostic(
                code="run_failed",
                agent=self.name,
                stage="stream",
                message=f"PydanticAIAgent run failed: {e}",
                details={"exception_type": type(e).__name__},
            ))
