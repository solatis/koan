# Agent-type system prompts -- one per agent role.
#
# These are delivered via --system-prompt at spawn time and persist for
# the entire agent lifetime. They carry identity, persistent knowledge,
# and cross-phase capabilities.
#
# Phase-specific role context (PHASE_ROLE_CONTEXT in each phase module)
# is a separate layer injected at step 1 via koan_complete_step.

from .orchestrator import SYSTEM_PROMPT as ORCHESTRATOR_SYSTEM_PROMPT
from .executor import SYSTEM_PROMPT as EXECUTOR_SYSTEM_PROMPT
from .scout import SYSTEM_PROMPT as SCOUT_SYSTEM_PROMPT

AGENT_TYPE_PROMPTS: dict[str, str] = {
    "orchestrator": ORCHESTRATOR_SYSTEM_PROMPT,
    "executor": EXECUTOR_SYSTEM_PROMPT,
    "scout": SCOUT_SYSTEM_PROMPT,
}
