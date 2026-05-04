# CommandLineAgent -- wraps koan.runners.Runner instances behind the Agent Protocol.
#
# Covers codex and gemini runner types. Claude uses ClaudeSDKAgent (koan/agents/claude.py)
# since M2; koan/runners/claude.py is deleted. ClaudeRunner references and the
# RunnerError translation block are removed.
#
# ALL koan.runners imports are lazy (inside functions/methods). This breaks the
# otherwise circular import chain: codex.py and gemini.py import AgentDiagnostic
# from koan.agents.base, which triggers koan.agents.__init__, which loads this
# module, which would re-import codex/gemini if any runner imports were at module
# level.

from __future__ import annotations

import asyncio
import asyncio.subprocess
from typing import TYPE_CHECKING, AsyncIterator

from ..logger import get_logger
from ..types import AgentInstallation, ModelInfo
from .base import AgentDiagnostic, AgentError, AgentOptions

if TYPE_CHECKING:
    from ..runners.base import Runner, StreamEvent

log = get_logger("command_line_agent")


# -- Post-build args helpers ---------------------------------------------------
# These helpers were previously in koan/subagent.py. They are pure functions
# that compose runner-specific CLI flags; no I/O, no globals except
# CLAUDE_TOOL_WHITELISTS from koan.subagent (imported at call time to avoid
# a circular import).


def _claude_post_build_args(
    role: str,
    run_dir: str,
    project_dir: str,
    additional_dirs: list[str],
) -> list[str]:
    """Compose claude-only post-build args: tool whitelist, slash-command disable,
    strict MCP config, additional directories, and permission mode.

    Returns a list of argv entries to append to a claude command. Pure function --
    no I/O, no globals beyond the CLAUDE_TOOL_WHITELISTS module constant.

    project_dir is listed before run_dir so the project is searched first.
    additional_dirs (each --add-dir <PATH> at koan run startup) are emitted
    after run_dir, in the order the user specified them. Empty strings
    anywhere in the input are skipped to avoid passing --add-dir "".
    """
    # Import here to avoid circular import: subagent.py imports from agents/,
    # so agents/ must not import from subagent.py at module level.
    from ..subagent import CLAUDE_TOOL_WHITELISTS

    args: list[str] = []
    whitelist = CLAUDE_TOOL_WHITELISTS.get(role)
    if whitelist is not None:
        args.extend(["--tools", whitelist])
    # --disable-slash-commands and --strict-mcp-config dropped in M2;
    # ClaudeSDKAgent owns the Claude path and does not use these CLI flags.
    # Add project and run directories so the CLI can read/edit files in both
    # locations without prompting; acceptEdits gates writes at the tool level.
    if project_dir:
        args.extend(["--add-dir", project_dir])
    if run_dir:
        args.extend(["--add-dir", run_dir])
    for extra in additional_dirs:
        if extra:
            args.extend(["--add-dir", extra])
    # acceptEdits is safe for all roles: the CLAUDE_TOOL_WHITELISTS already
    # restrict which roles receive Write/Edit in their tool vocabulary, so
    # scouts cannot write even though the permission mode is permissive.
    args.extend(["--permission-mode", "acceptEdits"])
    args.extend(["--allowedTools", "mcp__koan__*,Bash"])
    return args


def _codex_post_build_args(
    run_dir: str,
    project_dir: str,
    additional_dirs: list[str],
) -> list[str]:
    """Compose codex-only post-build args: --add-dir for project, run, and extras.

    Each directory becomes a separate --add-dir <DIR> flag, matching codex
    exec's CLI shape ("Additional directories that should be writable
    alongside the primary workspace"). Empty strings are skipped.

    project_dir comes first so codex treats it as the primary workspace
    conceptually, even though the actual primary is established by the
    subprocess cwd in spawn_subagent.
    """
    args: list[str] = []
    for d in (project_dir, run_dir, *additional_dirs):
        if d:
            args.extend(["--add-dir", d])
    return args


def _gemini_post_build_args(
    run_dir: str,
    project_dir: str,
    additional_dirs: list[str],
) -> list[str]:
    """Compose gemini-only post-build args: --include-directories for project,
    run, and extras.

    Each directory becomes a separate --include-directories <DIR> flag.
    Gemini also accepts comma-separated values, but the repeatable form
    avoids escaping concerns when paths contain commas. Empty strings
    are skipped.
    """
    args: list[str] = []
    for d in (project_dir, run_dir, *additional_dirs):
        if d:
            args.extend(["--include-directories", d])
    return args


# -- CommandLineAgent ----------------------------------------------------------

class CommandLineAgent:
    """The wrapper around koan.runners.Runner for command-line subprocess agents.

    Covers codex and gemini. Claude uses ClaudeSDKAgent (M2 cutover);
    koan/runners/claude.py is deleted.

    Lifecycle: one instance per subagent spawn. run(options) is called once;
    the caller iterates the yielded StreamEvents until the generator returns.
    After run() returns, exit_code and stderr_output are populated.
    """

    def __init__(self, runner: Runner, subagent_dir: str = "") -> None:
        """Create a CommandLineAgent wrapping the given Runner.

        subagent_dir is forwarded to build_command for runners that need it
        (GeminiRunner writes .gemini/settings.json there). It is also stored
        for runners that receive it at construction time (GeminiRunner).

        The agent's name is taken from runner.name so that the caller can
        gate on 'claude' / 'codex' / 'gemini' without inspecting the runner
        class directly.
        """
        self._runner = runner
        self._subagent_dir = subagent_dir
        self.name: str = runner.name

        # Set by run() after the subprocess is spawned.
        self._proc: asyncio.subprocess.Process | None = None
        self._exit_code: int | None = None
        self._stderr_output: str = ""

        # Set by register_process() before run() is called. Populated into the
        # registry inside run() as soon as self._proc is assigned.
        self._proc_registry: dict | None = None
        self._proc_registry_key: str = ""

    async def run(self, options: AgentOptions) -> AsyncIterator[StreamEvent]:
        """Spawn the subprocess, stream events, and wait for exit.

        Builds the command via self._runner.build_command, appends per-runner
        post-build args, spawns the subprocess, and yields StreamEvents from
        stdout. Stderr is drained concurrently. After stdout EOF, waits for
        the process and stores the exit code.

        Note: this is an async generator; the caller must iterate it to
        completion to ensure cleanup (proc.wait, stderr drain) runs.

        codex and gemini runners raise AgentError directly from build_command;
        RunnerError translation is no longer needed (claude.py deleted in M2).
        """
        installation = options.installation
        model = options.model
        thinking = options.thinking

        # Build the subprocess command. AgentError propagates naturally to
        # spawn_subagent; no translation wrapper needed after M2.
        if installation is not None and model is not None and thinking is not None:
            cmd = self._runner.build_command(
                options.boot_prompt,
                options.mcp_url,
                installation,
                model,
                thinking,
                system_prompt=options.system_prompt,
            )
        else:
            # Legacy/test path: installation or model not available.
            # build_command receives positional boot_prompt + mcp_url only.
            cmd = self._runner.build_command(
                options.boot_prompt,
                options.mcp_url,
                model or "",
                system_prompt=options.system_prompt,
            )

        # Append per-runner post-build args (directory scoping, permission mode).
        runner_name = self._runner.name
        if runner_name == "claude":
            cmd.extend(_claude_post_build_args(
                role=options.role,
                run_dir=options.run_dir,
                project_dir=options.project_dir,
                additional_dirs=options.additional_dirs,
            ))
        elif runner_name == "codex":
            cmd.extend(_codex_post_build_args(
                run_dir=options.run_dir,
                project_dir=options.project_dir,
                additional_dirs=options.additional_dirs,
            ))
        elif runner_name == "gemini":
            cmd.extend(_gemini_post_build_args(
                run_dir=options.run_dir,
                project_dir=options.project_dir,
                additional_dirs=options.additional_dirs,
            ))

        log.debug(
            "spawn command: role=%s runner=%s argc=%d cmd[0]=%s",
            options.role, runner_name, len(cmd), cmd[0] if cmd else "",
        )

        # Spawn subprocess. limit= raises asyncio's per-line StreamReader buffer
        # above the 64 KB default; large thinking blocks and tool results exceed it.
        spawn_cwd = options.cwd or self._subagent_dir or None
        self._proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=spawn_cwd,
            limit=4 * 1024 * 1024,
        )

        # Register the process into the active-process registry immediately
        # after spawn so the shutdown path can cancel it.
        if self._proc_registry is not None:
            self._proc_registry[self._proc_registry_key] = self._proc

        # Drain stderr concurrently so it does not block stdout iteration.
        stderr_task = asyncio.create_task(self._drain_stderr())

        # Stream stdout line by line, translate to StreamEvents.
        assert self._proc.stdout is not None
        async for raw in self._proc.stdout:
            line = raw.decode("utf-8", errors="replace").rstrip("\n")
            try:
                events = self._runner.parse_stream_event(line)
            except Exception as exc:
                log.warning(
                    "parse_stream_event failed for runner=%s: %s",
                    runner_name, exc,
                )
                # Skip this line; spawn_subagent degrades in-flight tools at EOF
                # when call_ids_by_block is non-empty.
                continue
            for ev in events:
                yield ev

        # Stdout EOF: wait for the process and record exit code.
        self._exit_code = await self._proc.wait()
        self._stderr_output = await stderr_task

    async def _drain_stderr(self) -> str:
        """Drain stderr to a string and return it.

        Called as a concurrent task during run() so stderr reads do not
        block stdout iteration.
        """
        assert self._proc is not None
        assert self._proc.stderr is not None
        buf: list[str] = []
        async for raw in self._proc.stderr:
            buf.append(raw.decode("utf-8", errors="replace"))
        return "".join(buf)

    async def interrupt(self) -> None:
        """Not supported on command-line agents.

        Codex and gemini have no in-process interrupt mechanism. Claude's
        interrupt will be implemented on ClaudeSDKAgent in M2.
        """
        raise NotImplementedError(
            "interrupt() is not supported by CommandLineAgent; "
            "it will be implemented on ClaudeSDKAgent in M2"
        )

    async def compact(self) -> None:
        """Not supported on command-line agents.

        The Claude Agent SDK does not yet expose a programmatic compact() surface.
        Codex and gemini have no equivalent.
        """
        raise NotImplementedError(
            "compact() is not supported by CommandLineAgent or any M1 agent"
        )

    def register_process(self, registry: dict, agent_id: str) -> None:
        """Register the agent's subprocess into the active-process registry.

        Called by spawn_subagent before iterating run() so that the shutdown
        path can cancel the process. Stores the registry reference; run()
        populates the entry as soon as the subprocess is spawned.

        If run() has already spawned the process (rare race), update immediately.
        """
        self._proc_registry = registry
        self._proc_registry_key = agent_id
        if self._proc is not None:
            registry[agent_id] = self._proc

    @property
    def exit_code(self) -> int | None:
        """Exit code of the subprocess. None until run() completes."""
        return self._exit_code

    @property
    def stderr_output(self) -> str:
        """Accumulated stderr from the subprocess. Empty string until run() completes."""
        return self._stderr_output

    @classmethod
    def list_models(cls, installation: AgentInstallation) -> list[ModelInfo]:
        """Return the model list for the given installation.

        Dispatches to the appropriate Runner's list_models without instantiating
        a full agent (no subprocess spawn). Used by koan/probe.py to populate
        ProbeResult.models at startup.

        Runner classes are imported lazily to avoid circular imports at module level.
        """
        runner_type = installation.runner_type
        binary = installation.binary
        try:
            if runner_type == "claude":
                # ClaudeSDKAgent owns the Claude path in M2; ClaudeRunner deleted.
                from .claude import ClaudeSDKAgent  # noqa: PLC0415
                return ClaudeSDKAgent.list_models(installation)
            elif runner_type == "codex":
                from ..runners.codex import CodexRunner  # noqa: PLC0415
                return CodexRunner().list_models(binary)
            elif runner_type == "gemini":
                from ..runners.gemini import GeminiRunner  # noqa: PLC0415
                return GeminiRunner(subagent_dir="").list_models(binary)
        except Exception:
            pass
        return []
