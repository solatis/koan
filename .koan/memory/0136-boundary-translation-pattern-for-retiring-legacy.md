---
title: Boundary-translation pattern for retiring legacy types across milestones --
  intermediate milestones translate at the abstraction boundary, final milestone removes
  the type and the translation block in one change
type: decision
created: '2026-05-02T07:31:21Z'
modified: '2026-05-02T07:31:21Z'
related:
- 0130-agent-abstraction-in-koanagents-replaces-runner.md
- 0114-safe-deletion-patterns-for-milestone-driven-removals-migrate-callers-before-delete-total-deletion-in-one-change-negative-presence-assertions-why-comments-at-deletion-sites-replace-not-repurpose.md
---

The Claude Agent SDK migration in koan (`koan/agents/command_line.py`, `koan/runners/base.py`) demonstrated a boundary-translation pattern for retiring legacy types across multiple milestones. On 2026-04-29, the agent-abstraction milestone introduced the `Agent` Protocol and `AgentError` while leaving `koan/runners/claude.py` and its `RunnerDiagnostic` / `RunnerError` types intact (intentionally out of scope for that milestone). The first executor run left `RunnerDiagnostic` and `RunnerError` defined in `koan/runners/base.py` rather than deleting them. The agent's exec-review accepted this as the canonical first-milestone shape: `koan/runners/claude.py` still imported `RunnerError` to raise on subprocess failures, and `CommandLineAgent.run()` translated `RunnerError -> AgentError` at the boundary so callers up the stack saw only the new type. On 2026-04-30, the SDK-adapter milestone deleted `koan/runners/claude.py`, `RunnerDiagnostic`, and `RunnerError` in one change; the dead `RunnerError` translation block in `CommandLineAgent.run()` was removed in the same milestone because codex and gemini already raised `AgentError` directly. On 2026-04-30, user adopted the pattern: when a multi-milestone migration retires a legacy type but an intermediate milestone leaves a not-yet-migrated subsystem still raising it, translate at the new abstraction's boundary, and delete the translation block alongside the legacy type when the final milestone removes it. The benefit: each intermediate milestone ships in a working state with the test suite green; no transitive module loses access to the new type during the migration.
