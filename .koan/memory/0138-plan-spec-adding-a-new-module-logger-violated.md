---
title: Plan-spec adding a new module logger violated brief.md Out of Scope; plan-review
  caught it by walking the Out of Scope list
type: lesson
created: '2026-05-04T07:56:15Z'
modified: '2026-05-04T07:56:15Z'
related:
- 0117-plan-review-reviewer-scope-narrowed-drop-mechanical.md
- 0118-plan-spec-and-plan-review-require.md
---

This entry records a planning failure during a koan plan workflow on 2026-05-04 addressing steering observability and naming hygiene. The intake phase had explicitly enumerated in `brief.md` Out of Scope: "Adding any new logger names (e.g. `koan.steering.trace`). User confirmed: DEBUG level on existing loggers is sufficient." The user had picked the "DEBUG -- silent by default" option over the "Dedicated logger" option at intake.

Despite this, plan-spec wrote a directive in `plan.md` instructing the executor to add `from ..logger import get_logger` and `log = get_logger("steering")` to `koan/agents/steering.py`, with the rationale "the file currently has no logger". The plan introduced exactly what the brief's Out of Scope had excluded. Root cause: plan-spec rationalized the new logger as a pragmatic file-scope addition rather than recognizing that any new `koan.steering*` namespace logger fell under the user's rejected dedicated-logger option.

Plan-review caught the violation by walking brief.md's Out of Scope section line by line and matching each plan directive against each Out of Scope item. The fix relocated the not-primary observability into the two existing callers (`koan/agents/claude.py post_tool_use_hook` using `koan.claude_sdk_agent`; `koan/web/mcp_endpoint.py _drain_and_append_steering` using `koan.mcp`) and made the steering.py directive a docstring-only update. The corrected plan executed cleanly.

Lesson for plan-review: brief.md Out of Scope is a higher-precedence enforcement tool than docstring discipline or approach soundness; walk it line by line and match each plan directive against each Out of Scope item. A plan rationalizing why an Out of Scope item should not apply to a specific case is itself the violation -- the brief is frozen and is the authority.
