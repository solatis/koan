---
title: Removing koan_yield silently dropped the UX payload its arguments and result
  carried, not just its control-flow role
type: lesson
created: '2026-06-04T14:20:01Z'
modified: '2026-06-04T14:20:01Z'
related:
- 0158-koanyield-removed-the-agent-loops-terminal-text.md
---

When the `koan_yield` tool was removed in favor of the agent loop's terminal-text hand-back, three things it had silently carried were dropped with it: the structured next-phase suggestions shown on the hand-back card (the YieldPanel options), binary-attachment delivery when the user resumes, and the `tool_attachments` audit event. Root cause: `koan_yield` was treated as pure control flow ("hand back to the user") when its arguments and result were also carrying UX payload, so removing the control-flow role removed the payload with it. Prevention: before deleting any tool, inventory every field its arguments and its result carried and find a new home for each, separately from re-homing its control-flow role. The fix re-derived the suggestions deterministically from the workflow's phase-transition table (`build_phase_suggestions`) rather than reintroducing a tool, and restored the attachment manifest on the in-process resume path.
