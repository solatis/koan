# Tool policy: allowlist data and per-(role, phase) toolset composition.
#
# ToolPolicy carries the allowlist tables (formerly in koan/lib/permissions.py,
# inlined here in M1 when that module was deleted). compose_toolset reads them
# once per (role, phase) to build the registered toolset for PydanticAIAgent.run(),
# replacing call-time permission gating with construction-time vocabulary
# restriction -- disallowed tools never enter the model's context.
#
# Composition is per (role, phase), NOT per step: the tool set stays byte-stable
# within a phase so it does not invalidate the tool-definition cache at each step
# boundary. The lone legacy step-level gate (brief-generation step 1) has no
# active-workflow consumer and is dropped.

from __future__ import annotations

from dataclasses import dataclass


# -- Permission tables (single source of truth for toolset composition) -------
# These were in koan/lib/permissions.py; inlined here in M1 when the fence
# module was deleted. The data survives -- only the check_permission gate is gone.

# Non-bash read tools -- unconditionally allowed for all roles.
_NON_BASH_READ_TOOLS: frozenset[str] = frozenset({"read", "grep", "glob", "find", "ls"})

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
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
        "koan_artifact_write",
        "koan_artifact_edit",
        "koan_memory_propose",
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
    "intake", "core-flows",
    "tech-plan-spec", "tech-plan-review",
    "ticket-breakdown", "cross-artifact-validation",
    "plan-spec", "plan-review",
    "milestone-spec", "milestone-review",
    "curation",
    "frame",
})

_ORCHESTRATOR_STORY_TOOLS: frozenset[str] = frozenset({
    "koan_select_story", "koan_complete_story",
    "koan_retry_story", "koan_skip_story",
})

_ORCHESTRATOR_BASH_PHASES: frozenset[str] = frozenset({
    "execution", "implementation-validation",
    "exec-review",
    "frame",
})


@dataclass(frozen=True)
class ToolPolicy:
    """Retained allowlist data from the deleted check_permission fence.

    Pure data structure; no enforcement logic of its own. compose_toolset
    reads it once per (role, phase) to build the registered toolset,
    replacing check_permission's call-time gate with registration-time
    vocabulary restriction.

    Fields:
        role_tools: Per-role frozensets of always-available tools (phase-
            conditional tools excluded -- they are added by compose_toolset).
        universal_tools: Tools allowed for every role in every phase
            (koan_memory_status, koan_search, koan_artifact_list,
            koan_artifact_read).
        read_tools: Non-bash file tools always allowed for all roles
            (read, grep, glob, find, ls).
        bash_phases: Phases where bash is allowed for the orchestrator role.
            Non-orchestrator roles always have bash.
        scout_phases: Phases where koan_request_scouts is allowed for the
            orchestrator. Maps to _ORCHESTRATOR_SCOUT_PHASES in permissions.py.
        executor_phases: Phases where koan_request_executor is allowed for
            the orchestrator. Distinct from story_phases because the executor
            tool is available in "execute" too (plan workflow), not only "execution".
        story_phases: Phases where the four story-management tools are allowed
            for the orchestrator (koan_select/complete/retry/skip_story).
    """

    role_tools: dict[str, frozenset[str]]
    universal_tools: frozenset[str]
    read_tools: frozenset[str]
    bash_phases: frozenset[str]
    scout_phases: frozenset[str]
    executor_phases: frozenset[str]
    story_phases: frozenset[str]


def build_tool_policy() -> ToolPolicy:
    """Construct ToolPolicy from the module-level allowlist tables.

    The tables are the single source of truth for toolset composition
    (formerly split between this module and the deleted koan/lib/permissions.py).

    The orchestrator's role_tools excludes the four phase-conditional tool sets
    (bash, koan_request_scouts, koan_request_executor, story tools) because
    compose_toolset adds them conditionally per phase. Non-orchestrator role_tools
    are used as-is from ROLE_PERMISSIONS.
    """
    # Orchestrator always-available tools: strip the four phase-conditional sets
    # so compose_toolset can add them only when the phase permits.
    # koan_request_executor is phase-gated to executor_phases (not always-on).
    orchestrator_always: frozenset[str] = (
        ROLE_PERMISSIONS["orchestrator"]
        - frozenset({"bash", "koan_request_scouts", "koan_request_executor"})
        - _ORCHESTRATOR_STORY_TOOLS
    )

    role_tools: dict[str, frozenset[str]] = {
        role: tools
        for role, tools in ROLE_PERMISSIONS.items()
        if role != "orchestrator"
    }
    role_tools["orchestrator"] = orchestrator_always

    # executor_phases is distinct from story_phases: the plan workflow uses
    # "execute" as its execution phase name, whereas story tools are "execution" only.
    return ToolPolicy(
        role_tools=role_tools,
        universal_tools=_UNIVERSAL_MEMORY_TOOLS | _UNIVERSAL_READ_TOOLS,
        read_tools=_NON_BASH_READ_TOOLS,
        bash_phases=_ORCHESTRATOR_BASH_PHASES,
        scout_phases=_ORCHESTRATOR_SCOUT_PHASES,
        executor_phases=frozenset({"execution", "execute"}),
        story_phases=frozenset({"execution"}),
    )


def compose_toolset(policy: ToolPolicy, role: str, phase: str) -> frozenset[str]:
    """Compute the allowed tool set for a (role, phase) pair.

    Mirrors check_permission's ALLOW logic per (role, phase) without any
    step-level gating (the legacy brief-generation step-1 gate targets a phase
    with no active workflow consumer and is dropped here -- composition is
    phase-granular so the tool set stays byte-stable within a phase, which is
    cache-friendly for the tool-definition prefix).

    Args:
        policy: The ToolPolicy built from permissions.py tables.
        role: SubagentRole string ("orchestrator", "executor", "scout", etc.).
        phase: Current workflow phase string (e.g. "plan-spec", "execution").

    Returns:
        frozenset of tool name strings that are allowed for this (role, phase).
    """
    # Base: non-bash read tools + universal tools + role-specific always-on tools.
    allowed: frozenset[str] = (
        policy.read_tools
        | policy.universal_tools
        | policy.role_tools.get(role, frozenset())
    )

    if role == "orchestrator":
        # bash is phase-gated for orchestrator; always allowed for other roles.
        if phase in policy.bash_phases:
            allowed |= frozenset({"bash"})
        # Scouting tools are only available in designated planning phases.
        if phase in policy.scout_phases:
            allowed |= frozenset({"koan_request_scouts"})
        # Executor tool is available in both plan-workflow "execute" and legacy "execution".
        if phase in policy.executor_phases:
            allowed |= frozenset({"koan_request_executor"})
        # Story-management tools are legacy execution-phase only.
        if phase in policy.story_phases:
            allowed |= _ORCHESTRATOR_STORY_TOOLS
    else:
        # Non-orchestrator roles always have bash (regardless of ROLE_PERMISSIONS).
        # This mirrors check_permission's unconditional bash allow for non-orchestrators.
        allowed |= frozenset({"bash"})

    return allowed
