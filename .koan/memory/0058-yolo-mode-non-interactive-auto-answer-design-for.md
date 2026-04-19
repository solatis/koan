---
title: yolo mode -- non-interactive auto-answer design for koan_yield and koan_ask_question
type: decision
created: '2026-04-19T08:10:27Z'
modified: '2026-04-19T13:38:28Z'
related:
- 0056-permission-mode-acceptedits-auto-approves-a-fixed.md
- 0057-claude-permissiondirectory-flags-composed-at.md
- 0061-directedphases-fixed-phase-sequence-for-eval.md
---

The `--yolo` non-interactive auto-answer mode in koan governs `koan_yield` and `koan_ask_question` in `koan/web/mcp_endpoint.py`. On 2026-04-19, Leon implemented the yolo auto-answer behavior as part of repurposing the previously no-op `--yolo` CLI flag (no-op since the 2026-04-19 Claude-CLI-flags change that moved permission-skipping to `--permission-mode acceptEdits`). The design was confirmed during an intake session on 2026-04-19.

For `koan_yield`: when `AppState.yolo` is `True`, the auto-response is resolved immediately without blocking. If `AppState.directed_phases` is not `None`, `_directed_yolo_response(directed_phases, current_phase)` is called first; it steers the orchestrator toward the next phase in the fixed list. When `directed_phases` is `None`, `_yolo_yield_response(suggestions)` is called using the following priority: (1) command text of the first suggestion with `recommended: True` and `id != "done"`, (2) command text of the first suggestion with `id != "done"`, (3) the string `"proceed"`. Leon selected suggestion-driven responses over a fixed return string, preferring that they kept the orchestrator on the workflow's intended path. On 2026-04-19, Leon added directed mode to give eval tests explicit phase-sequence control without relying on orchestrator interpretation of suggestion commands.

For `koan_ask_question`: after `enqueue_interaction` created the blocking future, `_yolo_ask_answer(questions)` was called to synthesize answers and `future.set_result(...)` was called before `await future`, causing it to resolve synchronously without blocking. Per question, the recommended option's label was selected; when no option carried `recommended: True`, the string `"use your best judgement"` was returned as free-form text. Leon confirmed the free-form fallback during intake, preferring to give the orchestrator latitude over forced arbitrary selection.

Both tools continued to emit their projection events (`yield_started` and `questions_asked`) before the yolo branch fired, so UI interaction cards appeared and closed immediately. This was confirmed during intake when Leon selected the "emit normal events, resolve immediately" option.
