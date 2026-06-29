---
title: Verify executor scope by find -mmin (or content-grep under concurrent editing),
  not git diff --stat, in a dog-fooded dirty working tree
type: procedure
created: '2026-06-08T08:26:14Z'
modified: '2026-06-29T08:48:57Z'
related:
- '0167'
- '0012'
---

When koan is dog-fooded on its own repository, the working tree frequently carries a large pre-existing uncommitted changeset from unrelated in-flight work. In that situation `git diff --stat` conflates the just-run executor's edits with every pre-existing dirty file and cannot show what the executor actually changed. On 2026-06-08, verifying a config-file conversion, `git diff --stat` reported 43 changed files while the executor had touched only 6; the rest was an unrelated, in-flight uncommitted changeset. The reliable first technique during exec-review (or any post-execution scope check) is to isolate the executor's edits by modification time -- e.g. `find koan tests docs -type f -mmin -20` -- and verify that set against the plan's intended file list. This also confirms out-of-scope guards held, since files outside the mtime window were demonstrably untouched. Caveat: scope the `find` to source directories, because an mtime window also captures files the orchestrator/curator itself wrote (run artifacts, the memory index). Second caveat, observed when the working tree was being edited CONCURRENTLY by another process during a dog-fooded run: `find -mmin` is then ALSO unreliable, because the unrelated concurrently-edited files carry recent mtimes too -- an ~80-file concurrent provider/connections changeset appeared entirely inside a tight mtime window. When concurrent editing is possible, isolate the change by CONTENT GREP for its signature instead -- grep the dirty files for the new symbols or terms the change introduces (a new function or field name); files that do not contain the change's signature are not part of it, regardless of mtime or git status.
