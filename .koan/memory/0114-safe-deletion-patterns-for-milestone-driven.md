---
title: Safe deletion patterns for milestone-driven removals -- migrate-callers-before-delete,
  total-deletion-in-one-change, negative-presence assertions, why-comments at deletion
  sites, replace-not-repurpose
type: procedure
created: '2026-04-26T09:34:10Z'
modified: '2026-04-26T09:34:10Z'
related:
- 0037-code-comment-vs-memory-entry-filter.md
---

On 2026-04-26, the koan codebase accumulated several safe-deletion patterns while retiring `koan_artifact_propose`, `_render_review_payload`, `artifact_review_future`, `phase_summaries`, `format_phase_complete`, and the inline-review frontend molecules (`ArtifactReviewPin`, `ReviewBlock`, `ReviewComment`, `ReviewCommentInput`, `ReviewEvent`). Leon's plan-spec codified the patterns; execution validated them (full test suite green, `npx tsc --noEmit` clean). The patterns:

(1) **Migrate callers BEFORE deleting tools.** Plan steps migrated phase prompts (`milestone_spec.py`, `plan_spec.py`), the orchestrator system prompt (`koan/prompts/orchestrator.py`), and the permission fence (`koan/lib/permissions.py`) from `koan_artifact_propose` to `koan_artifact_write`; only then was the tool deleted. Tests stayed green throughout because no caller was orphaned.

(2) **Total-deletion in one change for coupled mechanisms.** The `phase_summaries` retirement removed the field on `Run` + the fold case + the `phase_summary_captured` event + the capture block in `koan_yield` + the third source in `_compose_rag_anchor` + the chat-synthesis section in `intake.py`'s Summarize step ALL in one change, avoiding dead prose / dead code in any gap.

(3) **Negative-presence assertions in tests.** Pattern: a test that asserts a deleted symbol is no longer importable, e.g. `test_format_phase_complete_removed`. Applied to ensure `koan_artifact_propose` not importable from `koan.web.mcp_endpoint`, `phase_summaries` not in `Run.model_fields`, deleted molecule symbols not present in `frontend/src/`.

(4) **"Why" comments at deletion sites mark previously-stable contracts.** Example: the residual comment in `koan/state.py` documenting where `artifact_review_future` lived; frontend deletion-site comments in `App.tsx` and `api/client.ts`. Extends the executor-rationale-comment doctrine recorded in `0037-code-comment-vs-memory-entry-filter-comment.md` to cover deletion sites.

(5) **Replace endpoints rather than repurpose.** `/api/artifact-review` -> `/api/artifact-comment` was a clean break (new name reflects new semantics), not a same-route-repurpose. Recommended for future endpoint retirements.
