# Default-deny role-based permissions for koan subagents.
#
# Permission model:
#   1. READ_TOOLS (except bash) always allowed for all roles.
#   2. bash is always allowed for non-orchestrator roles; phase-gated for orchestrator.
#   3. ROLE_PERMISSIONS controls koan-specific tools and write/edit access.
#   4. Planning roles have write/edit path-scoped to the run directory.
#      Only executor has unrestricted write access.
#   5. The orchestrator role uses phase-aware permissions (current_phase parameter).
#
# Enforcement layers:
#   This fence gates MCP tool calls only.  Claude Code built-in tools (Read,
#   Write, Edit, Bash, etc.) are restricted at the CLI level via --tools
#   whitelists in subagent.py (CLAUDE_TOOL_WHITELISTS).  The two layers are
#   complementary: --tools controls which built-in tools exist in the model's
#   context; this fence controls which MCP tools are callable per role/phase.
#
#   Path-scoping for write/edit (below) validates paths when called through
#   the MCP endpoint.  Built-in Write/Edit bypass MCP entirely, so path
#   scoping for those relies on prompt engineering and the --tools whitelist.
#
# Pure functions -- no I/O, no mutable state.

from __future__ import annotations

from pathlib import Path

from ..logger import get_logger

log = get_logger("permissions")

# -- Constants ----------------------------------------------------------------

# Tools that are always allowed regardless of role (except bash for orchestrator).
READ_TOOLS: frozenset[str] = frozenset({
    "bash", "read", "grep", "glob", "find", "ls",
})

# Non-bash read tools — unconditionally allowed for all roles including orchestrator.
_NON_BASH_READ_TOOLS: frozenset[str] = READ_TOOLS - {"bash"}

WRITE_TOOLS: frozenset[str] = frozenset({"edit", "write"})

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "intake": frozenset({
        "koan_complete_step",
        "koan_ask_question",
        "koan_request_scouts",
        "edit",
        "write",
    }),
    "scout": frozenset({
        "koan_complete_step",
    }),
    "orchestrator": frozenset({
        # Documentation of the tools the orchestrator may use;
        # actual allow/deny lives in _check_orchestrator_permission.
        # write/edit are intentionally absent -- all artifact mutations
        # flow through koan_artifact_propose per this task's design.
        "koan_complete_step",
        "koan_set_phase",
        "koan_yield",
        "koan_ask_question",
        "koan_request_scouts",
        "koan_request_executor",
        "koan_select_story",
        "koan_complete_story",
        "koan_retry_story",
        "koan_skip_story",
        "koan_memorize",
        "koan_forget",
        "koan_memory_status",
        "koan_search",
        "koan_reflect",
        "koan_artifact_propose",
        "koan_memory_propose",
        "bash",
    }),
    "planner": frozenset({
        "koan_complete_step",
        "koan_ask_question",
        "koan_request_scouts",
        "edit",
        "write",
    }),
    "executor": frozenset({
        "koan_complete_step",
        "koan_ask_question",
        "edit",
        "write",
        "bash",
    }),
}

PLANNING_ROLES: frozenset[str] = frozenset({
    "intake",
    "scout",
    "orchestrator",
    "planner",
})

STEP_1_BLOCKED_TOOLS: frozenset[str] = frozenset({
    "koan_request_scouts",
    "koan_ask_question",
    "write",
    "edit",
})

# Memory query tools -- always allowed for all roles in every phase.
# A single canonical fast-path is simpler and safer than adding these
# to every role's ROLE_PERMISSIONS entry (which would diverge over time).
_UNIVERSAL_MEMORY_TOOLS: frozenset[str] = frozenset({
    "koan_memory_status",
    "koan_search",
})

# Read-only artifact tools -- always allowed for all roles in every phase.
# Mirroring _UNIVERSAL_MEMORY_TOOLS pattern (memory entry 0053): a single
# frozenset avoids per-role divergence as roles evolve.
_UNIVERSAL_READ_TOOLS: frozenset[str] = frozenset({
    "koan_artifact_list",
    "koan_artifact_view",
})

# -- Orchestrator phase-specific constants ------------------------------------

_ORCHESTRATOR_SCOUT_PHASES: frozenset[str] = frozenset({
    "intake", "core-flows", "tech-plan", "ticket-breakdown",
    "cross-artifact-validation",
    "plan-spec", "plan-review",   # plan workflow phases
    # Curation: standalone directive may need scouts to gather source
    # material from the codebase. Postmortem directive forbids them
    # in prose.
    "curation",
})

_ORCHESTRATOR_STORY_TOOLS: frozenset[str] = frozenset({
    "koan_select_story", "koan_complete_story",
    "koan_retry_story", "koan_skip_story",
})

# Memory tools are available to the orchestrator in every phase.
# koan_reflect is orchestrator-only (unlike koan_search/koan_memory_status
# which are universal); it belongs here so the phase-aware fast-path allows
# it without duplicating the check in _check_orchestrator_permission.
_ORCHESTRATOR_MEMORY_TOOLS: frozenset[str] = frozenset({
    "koan_memorize", "koan_forget", "koan_memory_status",
    "koan_search", "koan_reflect",
})

_ORCHESTRATOR_BASH_PHASES: frozenset[str] = frozenset({
    "execution", "implementation-validation",
})


# -- Permission check ---------------------------------------------------------

def _check_orchestrator_permission(
    tool_name: str,
    current_phase: str | None,
    current_step: int | None,
    run_dir: str | None,
    tool_args: dict | None,
) -> dict:
    """Phase-aware permission check for the persistent orchestrator role.

    Called after non-bash READ_TOOLS have already been allowed by check_permission.
    This function handles bash (phase-gated) and all koan tool permissions.
    """
    phase = current_phase or ""

    # Non-bash read tools: unconditionally allowed (already handled in check_permission,
    # but guard here too for direct callers).
    if tool_name in _NON_BASH_READ_TOOLS:
        log.debug(
            "permission allow: role=orchestrator tool=%s phase=%s step=%s",
            tool_name, phase, current_step,
        )
        return {"allowed": True, "reason": None}

    # bash — execution and implementation-validation only
    if tool_name == "bash":
        if phase in _ORCHESTRATOR_BASH_PHASES:
            log.debug(
                "permission allow: role=orchestrator tool=bash phase=%s step=%s",
                phase, current_step,
            )
            return {"allowed": True, "reason": None}
        reason = f"bash is not available in phase '{phase}'"
        log.debug(
            "permission deny: role=orchestrator tool=bash phase=%s reason=%s",
            phase, reason,
        )
        return {"allowed": False, "reason": reason}

    # Always allowed base koan tools
    if tool_name in ("koan_complete_step", "koan_set_phase", "koan_yield"):
        log.debug(
            "permission allow: role=orchestrator tool=%s phase=%s step=%s",
            tool_name, phase, current_step,
        )
        return {"allowed": True, "reason": None}

    # Memory tools -- available to the orchestrator in every phase
    if tool_name in _ORCHESTRATOR_MEMORY_TOOLS:
        log.debug(
            "permission allow: role=orchestrator tool=%s phase=%s step=%s",
            tool_name, phase, current_step,
        )
        return {"allowed": True, "reason": None}

    # koan_ask_question — always allowed except brief-generation step 1
    if tool_name == "koan_ask_question":
        if phase == "brief-generation" and current_step == 1:
            reason = (
                "koan_ask_question is not available during the Read step (step 1). "
                "Complete koan_complete_step first to advance to the next step."
            )
            log.debug(
                "permission deny: role=orchestrator tool=koan_ask_question phase=%s reason=%s",
                phase, reason,
            )
            return {"allowed": False, "reason": reason}
        log.debug(
            "permission allow: role=orchestrator tool=koan_ask_question phase=%s step=%s",
            phase, current_step,
        )
        return {"allowed": True, "reason": None}

    # koan_request_scouts — planning phases only (not brief-generation)
    if tool_name == "koan_request_scouts":
        if phase in _ORCHESTRATOR_SCOUT_PHASES:
            log.debug(
                "permission allow: role=orchestrator tool=koan_request_scouts phase=%s step=%s",
                phase, current_step,
            )
            return {"allowed": True, "reason": None}
        reason = f"koan_request_scouts is not available in phase '{phase}'"
        log.debug(
            "permission deny: role=orchestrator tool=koan_request_scouts phase=%s reason=%s",
            phase, reason,
        )
        return {"allowed": False, "reason": reason}

    # koan_request_executor — execute and execution phases
    if tool_name == "koan_request_executor":
        if phase in ("execution", "execute"):
            log.debug(
                "permission allow: role=orchestrator tool=koan_request_executor phase=%s step=%s",
                phase, current_step,
            )
            return {"allowed": True, "reason": None}
        reason = f"koan_request_executor is not available in phase '{phase}'"
        log.debug(
            "permission deny: role=orchestrator tool=koan_request_executor phase=%s reason=%s",
            phase, reason,
        )
        return {"allowed": False, "reason": reason}

    # Story management tools — legacy execution phase only
    if tool_name in _ORCHESTRATOR_STORY_TOOLS:
        if phase == "execution":
            log.debug(
                "permission allow: role=orchestrator tool=%s phase=%s step=%s",
                tool_name, phase, current_step,
            )
            return {"allowed": True, "reason": None}
        reason = f"{tool_name} is only available during the execution phase"
        log.debug(
            "permission deny: role=orchestrator tool=%s phase=%s reason=%s",
            tool_name, phase, reason,
        )
        return {"allowed": False, "reason": reason}

    # koan_artifact_propose -- orchestrator-only, available in every phase.
    # write/edit are intentionally absent: all artifact mutations flow through
    # this tool so the review handshake cannot be bypassed.
    if tool_name == "koan_artifact_propose":
        log.debug(
            "permission allow: role=orchestrator tool=koan_artifact_propose phase=%s step=%s",
            phase, current_step,
        )
        return {"allowed": True, "reason": None}

    # koan_memory_propose -- orchestrator-only, available in every phase.
    # Parallels koan_artifact_propose: memory mutations flow through this tool
    # so the review handshake cannot be bypassed.
    if tool_name == "koan_memory_propose":
        log.debug(
            "permission allow: role=orchestrator tool=koan_memory_propose phase=%s step=%s",
            phase, current_step,
        )
        return {"allowed": True, "reason": None}

    reason = f"{tool_name} is not available for the orchestrator role"
    log.debug(
        "permission deny: role=orchestrator tool=%s phase=%s reason=%s",
        tool_name, phase, reason,
    )
    return {"allowed": False, "reason": reason}


def check_permission(
    role: str,
    tool_name: str,
    run_dir: str | None = None,
    tool_args: dict | None = None,
    current_step: int | None = None,
    current_phase: str | None = None,
) -> dict:
    """Return {"allowed": True/False, "reason": str|None}."""

    # Non-bash read tools always allowed for all roles.
    if tool_name in _NON_BASH_READ_TOOLS:
        return {"allowed": True, "reason": None}

    # Memory query tools -- always allowed for all roles (scouts and executors
    # need read-only memory access; placing this before the orchestrator branch
    # avoids duplicating it in _check_orchestrator_permission).
    if tool_name in _UNIVERSAL_MEMORY_TOOLS:
        log.debug(
            "permission allow: role=%s tool=%s phase=%s step=%s",
            role, tool_name, current_phase, current_step,
        )
        return {"allowed": True, "reason": None}

    # Read-only artifact tools -- always allowed for all roles in every phase.
    if tool_name in _UNIVERSAL_READ_TOOLS:
        log.debug(
            "permission allow: role=%s tool=%s phase=%s step=%s",
            role, tool_name, current_phase, current_step,
        )
        return {"allowed": True, "reason": None}

    # Orchestrator uses phase-aware permission logic (handles bash phase-gating).
    if role == "orchestrator":
        return _check_orchestrator_permission(tool_name, current_phase, current_step, run_dir, tool_args)

    # bash always allowed for non-orchestrator roles.
    if tool_name == "bash":
        log.debug(
            "permission allow: role=%s tool=bash phase=%s step=%s",
            role, current_phase, current_step,
        )
        return {"allowed": True, "reason": None}

    # brief-generation step 1 (Read) is read-only — phase-aware gate.
    if current_phase == "brief-generation" and current_step == 1 and tool_name in STEP_1_BLOCKED_TOOLS:
        reason = (
            f"{tool_name} is not available during the Read step (step 1). "
            "Complete koan_complete_step first to advance to the Draft step."
        )
        log.debug(
            "permission deny: role=%s tool=%s phase=%s reason=%s",
            role, tool_name, current_phase, reason,
        )
        return {"allowed": False, "reason": reason}

    # Unknown role: blocked under default-deny policy.
    if role not in ROLE_PERMISSIONS:
        log.warning("Unknown role blocked: role=%s tool=%s", role, tool_name)
        return {"allowed": False, "reason": f"Unknown role: {role}"}

    allowed_tools = ROLE_PERMISSIONS[role]

    if tool_name not in allowed_tools:
        reason = f"{tool_name} is not available for role {role}"
        log.debug(
            "permission deny: role=%s tool=%s phase=%s reason=%s",
            role, tool_name, current_phase, reason,
        )
        return {"allowed": False, "reason": reason}

    # Path-scope enforcement: planning roles may only write inside run dir.
    if tool_name in WRITE_TOOLS and role in PLANNING_ROLES:
        if run_dir and tool_args:
            raw_path = tool_args.get("path")
            if isinstance(raw_path, str):
                resolved_tool = Path(raw_path).resolve()
                resolved_run = Path(run_dir).resolve()
                if resolved_tool != resolved_run and not str(resolved_tool).startswith(str(resolved_run) + "/"):
                    log.warning(
                        "Write blocked: path outside run dir: role=%s tool=%s path=%s run=%s",
                        role, tool_name, raw_path, run_dir,
                    )
                    return {
                        "allowed": False,
                        "reason": f'{tool_name} path "{raw_path}" is outside run directory',
                    }
        log.debug(
            "permission allow: role=%s tool=%s phase=%s step=%s",
            role, tool_name, current_phase, current_step,
        )
        return {"allowed": True, "reason": None}

    log.debug(
        "permission allow: role=%s tool=%s phase=%s step=%s",
        role, tool_name, current_phase, current_step,
    )
    return {"allowed": True, "reason": None}
