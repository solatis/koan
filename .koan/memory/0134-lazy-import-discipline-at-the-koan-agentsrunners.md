---
title: Lazy-import discipline at the koan agents/runners boundary -- module-level
  imports of runner classes from koan/agents/ create a circular import
type: procedure
created: '2026-05-02T07:31:08Z'
modified: '2026-05-02T07:31:08Z'
related:
- 0130-agent-abstraction-in-koanagents-replaces-runner.md
---

The koan agent infrastructure (`koan/agents/`, `koan/runners/`) has a structural import cycle: `koan.runners/__init__.py` eagerly imports its submodules and codex/gemini import diagnostic types from `koan.agents.base`. On 2026-04-29, the first executor run for the agent-abstraction milestone of the Claude Agent SDK migration introduced module-level `__import__("koan.runners.codex", fromlist=["CodexRunner"]).CodexRunner` calls in `koan/agents/registry.py`. The transitive chain reached at agent-registry load time was `koan.state -> koan.projections -> koan.runners.base -> koan.runners/__init__.py -> koan.runners.codex -> koan.agents.base -> koan.agents/__init__.py -> koan.agents.registry`. When `koan.agents.registry` evaluated the `__import__` calls at module load, `koan.runners.codex` was mid-load and the partial module had no `CodexRunner` attribute yet, raising `AttributeError: partially initialized module ...` and aborting pytest collection. On 2026-04-29, the agent's exec-review revised the milestone plan to prescribe lazy imports inside method bodies as the canonical break; the resumption executor run on 2026-04-29 applied the fix and completed the milestone. On the same date, user accepted the rule that imports of runner classes inside `koan/agents/` must happen at method-body scope, not at module top-level -- specifically, `AgentRegistry.get_agent` performs `from koan.runners.codex import CodexRunner` inside its body, not at the top of `koan/agents/registry.py`. User extended the rule to the SDK import inside `ClaudeSDKAgent.run()`. Module-level imports of runner classes from inside `koan/agents/` re-create the cycle.
