# Tool policy: allowlist data and role-based toolset composition.
#
# ToolPolicy carries the allowlist tables (formerly in koan/lib/permissions.py,
# inlined here in M1 when that module was deleted). compose_toolset reads them
# once per role to build the registered toolset for PydanticAIAgent.run().
# Phase-appropriateness for the orchestrator's phase-conditional tools
# (bash, koan_request_scouts, koan_request_executor) is enforced at call time
# by phase_gate_message, which returns a recoverable error when invoked in a
# disallowed phase.
#
# Composition is per role, NOT per phase: the tool set stays byte-stable across
# all phases so it does not invalidate the tool-definition cache prefix at each
# phase boundary. The lone legacy step-level gate (brief-generation step 1) has
# no active-workflow consumer and is dropped.

from __future__ import annotations

from dataclasses import dataclass


# -- Permission tables (single source of truth for toolset composition) -------
# These were in koan/lib/permissions.py; inlined here in M1 when the fence
# module was deleted. The data survives -- only the check_permission gate is gone.

# Non-bash read tools -- unconditionally allowed for all roles.
_NON_BASH_READ_TOOLS: frozenset[str] = frozenset({"read", "grep", "glob", "find", "ls"})

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    # Roles: intake, scout, orchestrator, planner, executor, reviewer.
    # Reviewer is read-only: no write/edit, no scouts, no set_phase.
    # bash, universal memory tools, and koan_artifact_read/list are added
    # unconditionally for non-orchestrator roles by compose_toolset.
    #
    # The step-advancement tool was removed from all roles in M6; end-of-turn
    # is the advancement signal and the loop resolver drives step progression.
    "intake": frozenset({
        "koan_ask_question",
        "koan_request_scouts",
        "edit",
        "write",
    }),
    "scout": frozenset({
        # Scouts advance through steps by ending each turn; the loop delivers
        # the next step and terminates at exhaustion. No tool needed.
    }),
    "orchestrator": frozenset({
        # write/edit intentionally absent -- artifact mutations flow through
        # koan_artifact_write / koan_artifact_edit.
        "koan_set_phase",
        "koan_set_workflow",
        # koan_suggest_next: only the orchestrator hands back to a user;
        # scouts/executors terminate at step exhaustion, so they don't need it.
        "koan_suggest_next",
        "koan_ask_question",
        "koan_request_scouts",
        # koan_request_executor: always registered in the orchestrator's static
        # toolset; gated at call time to the execute phase via phase_gate_message
        # and _ORCHESTRATOR_EXECUTOR_PHASES.
        "koan_request_executor",
        # Story tools (koan_select/complete/retry/skip_story) removed: the legacy
        # "execution" phase that used them is deleted in M1.
        "koan_memorize",
        "koan_forget",
        "koan_memory_status",
        "koan_search",
        "koan_reflect",
        "koan_artifact_write",
        "koan_artifact_edit",
        # koan_memory_propose removed in M7: the orchestrator now writes memory
        # directly via koan_memorize/koan_forget; no propose/approve gate.
        "bash",
    }),
    "planner": frozenset({
        "koan_ask_question",
        "koan_request_scouts",
        "edit",
        "write",
    }),
    "executor": frozenset({
        "koan_ask_question",
        "edit",
        "write",
        "bash",
    }),
    # Reviewer is strictly read-only. koan_reflect is the only koan tool beyond
    # the universals (koan_memory_status/koan_search, koan_artifact_read/list)
    # and bash that compose_toolset adds unconditionally for non-orchestrators.
    # write/edit, koan_artifact_write/edit, koan_request_scouts, koan_set_phase
    # are intentionally absent.
    "reviewer": frozenset({
        "koan_reflect",
    }),
}

# Memory query tools -- always allowed for all roles in every phase.
_UNIVERSAL_MEMORY_TOOLS: frozenset[str] = frozenset({
    "koan_memory_status",
    "koan_search",
})

# Read-only artifact tools -- always allowed for all roles in every phase.
_UNIVERSAL_READ_TOOLS: frozenset[str] = frozenset({
    "koan_artifact_list",
    "koan_artifact_read",
})

_ORCHESTRATOR_SCOUT_PHASES: frozenset[str] = frozenset({
    # M6: plan-review, milestone-review, tech-plan-review removed -- those phases
    # are deleted and replaced by the mechanical reviewer sub-agent (M3). The
    # reviewer role itself does not use scouts (brief Decision 6).
    "intake", "core-flows",
    "tech-plan",
    "plan",
    "milestone",
    "curation",
    "frame",
})

# _ORCHESTRATOR_STORY_TOOLS removed in M1: the legacy "execution" phase and its
# four koan_*_story tools are dead code (bound to no active workflow since T4 Phases).

_ORCHESTRATOR_BASH_PHASES: frozenset[str] = frozenset({
    # "execution" and "implementation-validation" removed: legacy phases deleted in M1.
    # "execute" added in M5: the orchestrator runs inline conformance verification.
    # M6: "exec-review" removed -- that phase is deleted; inline review lives in execute.
    "execute",
    "frame",
})

# koan_request_executor is only useful in execute: need-to-know keeps the
# cached tool prefix lean in all other phases.
_ORCHESTRATOR_EXECUTOR_PHASES: frozenset[str] = frozenset({"execute"})


@dataclass(frozen=True)
class ToolPolicy:
    """Retained allowlist data from the deleted check_permission fence.

    Pure data structure; no enforcement logic of its own. compose_toolset
    reads it once per role to build the registered toolset. The three
    phase-conditional orchestrator tools (bash, koan_request_scouts,
    koan_request_executor) are always registered in the orchestrator's
    static toolset; phase_gate_message uses the *_phases fields to enforce
    call-time phase-appropriateness and return a recoverable error when
    they are invoked outside their allowed phases.

    Fields:
        role_tools: Per-role frozensets of registered tools. For the
            orchestrator this is the full ROLE_PERMISSIONS["orchestrator"]
            set (including bash, koan_request_scouts, koan_request_executor).
        universal_tools: Tools allowed for every role in every phase
            (koan_memory_status, koan_search, koan_artifact_list,
            koan_artifact_read).
        read_tools: Non-bash file tools always allowed for all roles
            (read, grep, glob, find, ls).
        bash_phases: Phases where bash is allowed for the orchestrator role;
            used by phase_gate_message. Non-orchestrator roles always have bash.
        scout_phases: Phases where koan_request_scouts is allowed for the
            orchestrator; used by phase_gate_message.
        executor_phases: Phases where koan_request_executor is allowed for
            the orchestrator; used by phase_gate_message.
    """

    role_tools: dict[str, frozenset[str]]
    universal_tools: frozenset[str]
    read_tools: frozenset[str]
    bash_phases: frozenset[str]
    scout_phases: frozenset[str]
    executor_phases: frozenset[str]


def build_tool_policy() -> ToolPolicy:
    """Construct ToolPolicy from the module-level allowlist tables.

    The tables are the single source of truth for toolset composition
    (formerly split between this module and the deleted koan/lib/permissions.py).

    role_tools is built directly from ROLE_PERMISSIONS for all roles; the
    orchestrator's entry includes bash, koan_request_scouts, and
    koan_request_executor because they are always registered in the static
    toolset. The *_phases fields feed phase_gate_message for call-time
    phase-appropriateness enforcement rather than controlling registration.
    """
    return ToolPolicy(
        role_tools=dict(ROLE_PERMISSIONS),
        universal_tools=_UNIVERSAL_MEMORY_TOOLS | _UNIVERSAL_READ_TOOLS,
        read_tools=_NON_BASH_READ_TOOLS,
        bash_phases=_ORCHESTRATOR_BASH_PHASES,
        scout_phases=_ORCHESTRATOR_SCOUT_PHASES,
        executor_phases=_ORCHESTRATOR_EXECUTOR_PHASES,
    )


def compose_toolset(policy: ToolPolicy, role: str) -> frozenset[str]:
    """Compute the registered tool set for a role.

    Builds a static, phase-independent vocabulary for the role so the
    tool-definition cache prefix stays byte-stable across all phases for
    the long-lived orchestrator. Phase-appropriateness for the orchestrator's
    phase-conditional tools (bash, koan_request_scouts, koan_request_executor)
    is enforced at call time by phase_gate_message rather than here.

    For non-orchestrator roles, bash is added unconditionally regardless of
    ROLE_PERMISSIONS (mirrors check_permission's unconditional bash allow).
    Orchestrator bash is already in ROLE_PERMISSIONS["orchestrator"] and
    therefore in policy.role_tools["orchestrator"].

    Args:
        policy: The ToolPolicy built from module-level allowlist tables.
        role: SubagentRole string ("orchestrator", "executor", "scout", etc.).

    Returns:
        frozenset of tool name strings that are registered for this role.
    """
    allowed: frozenset[str] = (
        policy.read_tools
        | policy.universal_tools
        | policy.role_tools.get(role, frozenset())
    )

    if role != "orchestrator":
        # Non-orchestrator roles always have bash; orchestrator gets it via
        # role_tools (already in ROLE_PERMISSIONS["orchestrator"]).
        allowed |= frozenset({"bash"})

    return allowed


def phase_gate_message(
    policy: ToolPolicy,
    role: str,
    phase: str,
    tool_name: str,
) -> str | None:
    """Return a denial message when tool_name is not allowed in the current phase.

    Only the orchestrator role has phase-conditional tools; all other roles
    short-circuit to None immediately. For the orchestrator, the three
    phase-conditional tools (bash, koan_request_scouts, koan_request_executor)
    are looked up against their respective phase allowlists. Any other tool
    name is always allowed (returns None).

    Args:
        policy: The ToolPolicy built from module-level allowlist tables.
        role: SubagentRole string for the calling agent.
        phase: Current workflow phase string (e.g. "plan", "execute").
        tool_name: The name of the tool being invoked.

    Returns:
        None when the call is permitted; a human-readable denial string when
        the tool is invoked in a disallowed phase.  The caller should return
        this message to the model as a recoverable error, never raise.
    """
    if role != "orchestrator":
        return None

    gate_map: dict[str, frozenset[str]] = {
        "koan_request_executor": policy.executor_phases,
        "koan_request_scouts": policy.scout_phases,
        "bash": policy.bash_phases,
    }
    allowed_phases = gate_map.get(tool_name)
    if allowed_phases is None:
        return None
    if phase in allowed_phases:
        return None
    return (
        f"The {tool_name!r} tool is not available in the {phase!r} phase."
        f" It is available only in: {', '.join(sorted(allowed_phases))}."
    )
