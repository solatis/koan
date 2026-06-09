---
title: Negative-presence shell verification uses grep -q + echo to avoid silent shell-pipeline
  failures
type: procedure
created: '2026-05-02T07:23:27Z'
modified: '2026-05-02T07:23:27Z'
related:
- 0114-safe-deletion-patterns-for-milestone-driven-removals-migrate-callers-before-delete-total-deletion-in-one-change-negative-presence-assertions-why-comments-at-deletion-sites-replace-not-repurpose.md
---

The koan executor (`koan/subagent.py`, executor task instructions written to `~/.koan/runs/<run>/subagents/executor-*/task.json`) runs Bash verification steps that often include negative-presence assertions -- "grep should find no matches, because the symbol was deleted". On 2026-04-30, during the executor run that deleted `koan/runners/claude.py`, a verification step used raw `grep -nE "from .*claude.*import (RunnerDiagnostic|RunnerError)" path/to/file.py` to assert the symbol was no longer present. When the symbol was absent, `grep` found no match, exited 1, and the shell pipeline propagated the non-zero exit. The executor reported run failure despite all source changes having succeeded. On 2026-04-30, the agent revised the resumption plan to use the form `grep -q PATTERN path/to/file.py && echo "STILL IMPORTABLE: FAIL"`. The `grep -q` exits 0 when matches exist and 1 when absent; the `&& echo` prints only on the match-exists path; the overall pipeline exits 0 in both outcomes. The printed marker became the failure signal, not the shell exit code. On the same date, user established the rule that future plan-spec phases prescribing Bash verification of deleted-symbol absence must use this form. Companion lesson from the same run: `tests/test_runners.py` imported `ClaudeRunner`; the original plan deleted `koan/runners/claude.py` before `tests/test_runners.py` was updated to drop its `TestClaudeRunner` classes, causing pytest collection to fail with `ImportError`. The corrected ordering codified in the resumption guidance: test cleanup before symbol deletion before verification -- "callers" of a deleted symbol includes test modules in addition to source modules.
