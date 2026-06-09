---
title: A clean-slate config-schema cutover is atomic across the schema root and every
  reader; size it by reader fan-out and stage it behind a boundary-translation shim
type: lesson
created: '2026-06-08T23:35:48Z'
modified: '2026-06-08T23:35:48Z'
related:
- 0136-boundary-translation-pattern-for-retiring-legacy.md
- 0169-reshaping-a-core-config-type-left-stale.md
- 0188-verify-executor-scope-by-recent-mtime-find-mmin.md
---

When koan rebuilt its provider/model config schema (the connections/configured-models/presets model in `koan/config.py` and `koan/types.py`, replacing `Profile`/`ProviderAuth`), the initial decomposition put the data-core reshape and the full web/projection/events seam rework (`koan/projections.py`, `koan/events.py`, `koan/web/app.py`) into a single milestone. milestone-review, after Leon directed it to size by actual work and complexity rather than file count, flagged that milestone as too large. Root cause: a hard-cutover schema change has wide reader fan-out -- deleting the old types forces every reader (projection folds, web endpoints, the agent registry, subagent plumbing) to migrate in the same change or the app fails to boot -- so the work is dominated by the reader sweep, which a file-count estimate understates. Prevention, which Leon directed: split the cutover with a temporary boundary-translation shim -- land the new data core first while a small adapter synthesizes the old views so the unchanged seam keeps working, then rework the seam and delete the shim together in a later milestone, so each milestone ships with the suite green. The same run re-confirmed that a missed reader of a deleted config type crashes app boot, and that executor scope is checked by recent mtime (`find -mmin`), not `git diff`, when the working tree is dirty.
