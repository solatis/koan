---
title: Stateless hash-anchored edit protocol (fnv1a32 line hash + ordinal) replaces
  exact-string-match editing in built-in edit and koan_artifact_edit
type: decision
created: '2026-06-07T04:01:58Z'
modified: '2026-06-07T04:01:58Z'
related:
- 0163-built-in-tool-output-must-match-the-metrics.md
---

koan's built-in `edit` tool and the `koan_artifact_edit` wrapper edit files by content-hash line anchors rather than by exact string match, implemented in the pure module `koan/tools/line_anchors.py`. An anchor is `fnv1a32(line)` rendered as 8 hex characters over the line content (indentation included, trailing newline excluded); hash collisions get a 1-based `~N` ordinal in file order. `read` emits each line as `{lineno}\t{anchor}` followed by the section sign U+00A7 (`§`) and `{content}`, and `edit(file_path, anchor, text, end_anchor=None, edit_type=...)` recomputes anchors from the current on-disk file at edit time, locates the line by hash (plus ordinal), and verifies the inline content against the current line before applying (a mismatch is a drift error telling the model to re-read). No anchor state is ever stored. Leon chose this stateless scheme in the task brief explicitly over dirac's stateful word-anchor scheme, to fit koan's stateless-algorithm preference; multi-edit batches stay safe by resolving every anchor against one file snapshot and applying in descending line order. Anchors are computed over the WHOLE file even when a read returns a slice, so a sliced read's anchors and an edit's recomputed anchors agree. The cutover was outright (a user decision during intake): the previous `old_string`/`new_string` exact-match mode was removed with no fallback in either the built-in `edit` or `koan_artifact_edit`, and affected tests migrated in the same pass. The anchored `read` format deliberately preserves the leading `{lineno}\t` prefix that the metrics parser in `koan/agents/pydantic_ai.py` keys on, so per-call `lines_read` stays exact.
