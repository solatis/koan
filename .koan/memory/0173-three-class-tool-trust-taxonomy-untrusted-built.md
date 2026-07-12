---
title: 'Three-class tool trust taxonomy: untrusted built-ins cap at limit (pre-emptive),
  trusted koan_artifact_* commands are exempt via limit=None, web tools are request-bounded'
type: decision
created: '2026-06-07T04:01:44Z'
modified: '2026-07-10T08:20:57Z'
related:
- 0157-tool-vocabulary-is-restricted-at-toolset.md
---

koan's in-process tool layer (`koan/tools/builtin_tools.py`, `koan/tools/koan_tools.py`) sorts tools into three trust classes that decide output-size handling, a model Leon set in the tool-layer task brief and refined during intake. (1) Untrusted built-ins — raw `read`, `grep`, `glob`, `bash` — touch arbitrary filesystem and shell and cap output pre-emptively at a model-facing `limit` (default `DEFAULT_LIMIT = 500`); generator-style processing stops as soon as `limit` records are collected, so remaining files/lines/paths are not processed. The raw `read` stays capped even for the orchestrator role: the motivating incident was an unguarded orchestrator `read` of a roughly 1 MB minified frontend bundle, so exempting the orchestrator's own raw read was rejected. (2) Trusted koan commands — `koan_artifact_read` / `koan_artifact_write` / `koan_artifact_edit` — operate only on run-dir artifacts koan itself authored and are bounded by prompting, so they are exempt from the output cap; `koan_artifact_read` calls `read_tool` with `limit=None` (both `artifact_read_core` and the model-facing `_koan_artifact_read` wrapper default to `None`), returning full content. The `limit=None` bypass is deliberately kept out of the model-facing `_read` tool signature — the model cannot pass `None` to un-limit a raw untrusted read; only the trusted artifact wrapper exposes it. (3) Web tools — `web_fetch` / `web_search` — are bounded by their own request parameters (`max_chars` / `max_results`) and are likewise exempt. A load-bearing consequence: because artifact reads are trusted and exempt, review phases do not page large artifacts and there is no higher review-phase read ceiling.
