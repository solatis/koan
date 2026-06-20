# Agent-type system prompts -- one per agent role.
#
# These are delivered via --system-prompt at spawn time and persist for
# the entire agent lifetime. They carry identity, persistent knowledge,
# and cross-phase capabilities.
#
# Phase-specific role context (PHASE_ROLE_CONTEXT in each phase module)
# is injected as the first step's turn prompt by the loop.

from .orchestrator import SYSTEM_PROMPT as ORCHESTRATOR_SYSTEM_PROMPT
from .executor import SYSTEM_PROMPT as EXECUTOR_SYSTEM_PROMPT
from .reviewer import SYSTEM_PROMPT as REVIEWER_SYSTEM_PROMPT
from .scout import SYSTEM_PROMPT as SCOUT_SYSTEM_PROMPT

AGENT_TYPE_PROMPTS: dict[str, str] = {
    "orchestrator": ORCHESTRATOR_SYSTEM_PROMPT,
    "executor": EXECUTOR_SYSTEM_PROMPT,
    "scout": SCOUT_SYSTEM_PROMPT,
    # Reviewer is a fresh-context, read-only sub-agent spawned mechanically by
    # artifact_write_core; its identity is delivered via this system prompt.
    "reviewer": REVIEWER_SYSTEM_PROMPT,
}
