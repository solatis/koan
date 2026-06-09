---
title: Verify executor scope by recent mtime (find -mmin), not git diff --stat, when
  dog-fooding koan in a dirty working tree
type: procedure
created: '2026-06-08T08:26:14Z'
modified: '2026-06-08T08:26:14Z'
related:
- '0167'
- '0012'
---

When koan is dog-fooded on its own repository, the working tree frequently carries a large pre-existing uncommitted changeset from unrelated in-flight work. In that situation `git diff --stat` conflates the just-run executor's edits with every pre-existing dirty file and cannot show what the executor actually changed. On 2026-06-08, verifying a config-file conversion, `git diff --stat` reported 43 changed files while the executor had touched only 6; the rest was an unrelated, in-flight uncommitted changeset. The reliable technique during exec-review (or any post-execution scope check) is to isolate the executor's edits by modification time -- e.g. `find koan tests docs -type f -mmin -20` -- and verify that set against the plan's intended file list, rather than trusting the cumulative git diff. This also confirms out-of-scope guards held, since files outside the mtime window were demonstrably untouched. Caveat: scope the `find` to source directories, because an mtime window also captures files the orchestrator/curator itself wrote (run artifacts, the memory index).
