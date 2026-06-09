# PydanticAIAgent: in-process agent implementing the existing Agent protocol.
#
# Drives one pydantic-ai agent.iter() run on a provider model (Gemini in M2,
# all four providers in M7) and translates the streamed graph events into koan's
# unchanged 8-type StreamEvent vocabulary. The translation layer is the
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
#
#  End node                           -> turn_complete (with RunUsage on usage field)
#
# tool_use_id = ToolCallPart.tool_call_id so spawn_subagent's call_id_by_tool_use_id
# correlation works unchanged.

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, AsyncIterator

from .base import AgentDiagnostic, AgentError, AgentOptions
from .events import StreamEvent

if TYPE_CHECKING:
    from ..types import ModelSpec


def _parse_read_result_from_content(content: str) -> dict | None:
    """Derive {lines_read, bytes_read} metrics from a cat -n formatted read result.

    Mirrors koan/agents/claude.py:_parse_read_result so that read tool results
    emitted by PydanticAIAgent carry the same metrics shape as the ClaudeSDKAgent
    path. Only read results (lines starting with a digit followed by a tab) are
    counted; non-matching lines are ignored. Returns None when no numbered lines
    are found (e.g. error string from read_tool).
    """
    if not content:
        return None
    lines = 0
    byte_total = 0
    any_numbered = False
    for raw_line in content.splitlines():
        stripped = raw_line.lstrip()
        tab_idx = stripped.find("\t")
        if tab_idx == -1:
            continue
        prefix = stripped[:tab_idx]
        if not prefix.isdigit():
            continue
        any_numbered = True
        content_part = stripped[tab_idx + 1:]
        lines += 1
        byte_total += len(content_part.encode("utf-8"))
    if not any_numbered:
        return None
    return {"lines_read": lines, "bytes_read": byte_total}


def _parse_grep_result_from_content(content: str) -> dict | None:
    """Derive {matches, files_matched} metrics from grep/glob tool output.

    Mirrors koan/agents/claude.py:_parse_grep_result. The authoritative format
    emitted by grep_tool is "Found N matches in M files"; glob_tool emits
    "Found N files" (files_matched == matches). Both are handled here.

    Returns None when the content does not look like grep/glob output
    (e.g. an error string from the tool).
    """
    import re
    if not content:
        return None
    first_line = content.splitlines()[0] if content else ""
    if not first_line.lower().startswith("found "):
        return None
    m = re.search(
        r"found\s+(\d+)\s+matches?(?:\s+in\s+(\d+)\s+files?)?",
        first_line,
        re.IGNORECASE,
    )
    if m:
        result: dict = {"matches": int(m.group(1))}
        if m.group(2) is not None:
            result["files_matched"] = int(m.group(2))
        return result
    m = re.search(r"found\s+(\d+)\s+files?", first_line, re.IGNORECASE)
    if m:
        n = int(m.group(1))
        return {"matches": n, "files_matched": n}
    return None


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

        Translates pydantic-ai's graph-node / stream events into koan's 8-type
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

        M3 toolset composition: the registered koan toolset is composed per
        (role, phase) via compose_toolset(build_tool_policy(), ...), so
        disallowed tools never enter the model's vocabulary (the permission-fence
        replacement).  The built-in toolset and deferred koan tools are also
        subject to composition; deferred tools are allowed by policy but absent
        from build_koan_toolset until M5/M6.

        M4 context-file injection: the project-directory context file
        (AGENTS.md > CLAUDE.md) is seeded into pending_context_files at loop
        start and injected before the first model request via a ProcessHistory
        capability. Subsequent subtree files are queued just-in-time by the
        path-bearing tools and injected before the next request.

        M4 metrics extension: grep and glob results carry {matches, files_matched}
        metrics derived from the "Found N matches in M files" / "Found N files"
        header so the projection fold populates AggregateGrepChild / AggregateGlobChild.
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

        # Resolve the full provider auth (secret + non-secret region/base_url) by
        # looking up the Connection by connection_id from the ModelSpec, then
        # calling resolve_provider_auth(connection, store).
        # The store is None only in tests that skip the credential path.
        store = self._app_state.provider_config.credential_store
        cfg = self._app_state.provider_config.config
        conn_id = self._model_spec.connection_id
        connection = next(
            (c for c in (cfg.connections if cfg else [])
             if c.id == conn_id),
            None,
        )
        # Raise only when a non-empty connection_id was specified but not found.
        # An empty connection_id means no connection was assigned (pre-M1 ModelSpec
        # or test path); fall back to resolving by provider type in that case.
        if connection is None and conn_id:
            raise AgentError(AgentDiagnostic(
                code="unconfigured",
                agent=self.name,
                stage="spawn",
                message=(
                    f"Connection '{conn_id}' not found in config. "
                    "Ensure the connection is configured before starting a run."
                ),
            ))
        if connection is not None:
            resolved = _adapter_mod.resolve_provider_auth(connection, store)
        else:
            # Pre-M1 fallback: no connection_id on spec (empty string).
            # Find the first connection of this provider type in the config
            # and resolve credentials by its connection id.  Requires
            # app_state.provider_config.config to carry a matching connection.
            # M4: removed type-keyed store.resolve() call; now finds the
            # connection by type from config.connections instead.
            conn_for_type = next(
                (c for c in (cfg.connections if cfg else [])
                 if c.type == self._model_spec.provider),
                None,
            )
            if conn_for_type is not None:
                resolved = _adapter_mod.resolve_provider_auth(conn_for_type, store)
            else:
                resolved = _adapter_mod.ResolvedProviderAuth(
                    api_key=None, region=None, base_url=None
                )

        # Build the provider model and settings from the resolved ModelSpec.
        try:
            model = _adapter_mod.build_model(
                self._model_spec,
                resolved.api_key,
                region=resolved.region,
                base_url=resolved.base_url,
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

        # Seed the project-directory context file so the first model request
        # always carries it, regardless of which files the model touches.
        # Uses options.project_dir (set by spawn_subagent) with a fallback to
        # app_state.run.project_dir; both may be "" in tests (safe -- skipped).
        from ..tools.context_files import discover_context_file, make_context_history_processor
        project_root = options.project_dir or self._app_state.run.project_dir
        if project_root:
            _proj_ctx_file = discover_context_file(project_root)
            if _proj_ctx_file and _proj_ctx_file not in agent_state.injected_context_files:
                agent_state.pending_context_files.append(_proj_ctx_file)

        # Build the history processor that drains pending_context_files before
        # each model request and injects them as <project_instructions> user
        # messages. ProcessHistory is the v2.0.0b6 replacement for the
        # deprecated history_processors kwarg; it calls before_model_request.
        from pydantic_ai.capabilities.process_history import ProcessHistory
        context_processor = make_context_history_processor(deps)
        capabilities = [ProcessHistory(context_processor)]

        # Compose toolsets per (role, phase) -- M3 fence replacement.
        # compose_toolset returns the allowed vocabulary; build_koan_toolset
        # registers only the intersection with implemented tools.  As of M6 the
        # koan toolset implements all live tools (the subagent-spawn tools landed
        # in M6, the interaction tools in M5); web_search/web_fetch land in M7.
        policy = build_tool_policy()
        allowed = compose_toolset(policy, options.role, self._app_state.run.phase)
        koan_toolset = build_koan_toolset(allowed_names=allowed)
        builtin_toolset = build_builtin_toolset()

        # Construct pydantic-ai Agent with instructions (v2 prefers instructions
        # over system_prompt for the byte-stable cache prefix).
        pai_agent: PAIAgent[ToolDeps, str] = PAIAgent(
            model=model,
            instructions=options.system_prompt,
            toolsets=[koan_toolset, builtin_toolset],
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
            # the same 8-type StreamEvent vocabulary documented above.
            from .loop import run_agent_loop
            async for ev in run_agent_loop(
                pai_agent, deps, options, self._app_state, agent_state,
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
