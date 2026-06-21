---
title: A stale dog-fooded koan daemon serves pre-refactor phase/tool names; phase-gated
  koan_artifact_write can crash in a non-origin phase while koan_artifact_edit does
  not
type: lesson
created: '2026-06-21T11:33:16Z'
modified: '2026-06-21T11:33:16Z'
related:
- 0167-when-dog-fooding-koan-on-its-own-development-a.md
- 0012-koan-is-dog-fooded-on-its-own-development-meta.md
- 0233-artifact-and-transition-tool-permission-failures.md
---

When developing koan with koan (dog-fooding), the long-lived orchestrator daemon serves the code it booted with, not the working tree or latest commit. While building the artifact permission gate in 2026-06 this surfaced concretely: a `koan_set_phase("tech-plan")` call was rejected because the running daemon still had the pre-refactor initiative phases (`tech-plan-spec`, `tech-plan-review`, `milestone-spec`, and the other separate `-review` phases) and the old `koan_artifact_view` tool name, whereas the committed `koan/lib/workflows.py` had collapsed those to bare-name phases (`tech-plan`, `milestone`, `plan`) and renamed the read tool to `koan_artifact_read`. Two practical consequences when restarting the daemon mid-run is not an option: navigate phases using the LIVE daemon's phase names, but write code and artifacts against the COMMITTED on-disk code, because spawned executor subagents read and edit the on-disk code, not the daemon's memory; and prefer `koan_artifact_edit` over `koan_artifact_write` for correcting an artifact while in a review phase, because in the pre-fix code `validate_write` is phase-gated (it checks `origin_phases` and raises `wrong_phase` from a non-origin phase, which propagates and crashes the run) while `validate_edit` carries no phase gate, so the edit succeeds. That crash mode was itself the target of the same 2026-06 change -- artifact and transition validation failures were converted to RETURN a recoverable envelope instead of raising -- so once a daemon reloads that code the workaround is unnecessary. Root cause: a long-lived process reflects the code it booted with, and koan's dog-fooding makes it easy to mistake the daemon's behavior for evidence about the current code.
