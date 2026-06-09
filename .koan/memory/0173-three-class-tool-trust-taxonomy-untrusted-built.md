---
title: 'Three-class tool trust taxonomy: untrusted built-ins carry a reject ceiling,
  trusted koan_artifact_* commands are exempt, web tools are request-bounded'
type: decision
created: '2026-06-07T04:01:44Z'
modified: '2026-06-07T04:01:44Z'
related:
- 0157-tool-vocabulary-is-restricted-at-toolset.md
---

koan's in-process tool layer (`koan/tools/builtin_tools.py`, `koan/tools/koan_tools.py`) sorts tools into three trust classes that decide output-size handling, a model Leon set in the tool-layer task brief and refined during intake. (1) Untrusted built-ins -- raw `read`, `grep`, `glob`, `bash` -- touch arbitrary filesystem and shell and carry a hard reject ceiling (over 500 lines or at least 10 KB). The raw `read` stays limited even for the orchestrator role: the motivating incident was an unguarded orchestrator `read` of a roughly 1 MB minified frontend bundle, so the alternative of exempting the orchestrator's own raw read was rejected. (2) Trusted koan commands -- `koan_artifact_read` / `koan_artifact_write` / `koan_artifact_edit` -- operate only on run-dir artifacts koan itself authored and are bounded by prompting, so they are exempt from the reject ceiling; `koan_artifact_read` keeps `offset`/`limit` for paging convenience but applies no hard reject (it calls `read_tool` with `enforce_limits=False`). (3) Web tools -- `web_fetch` / `web_search` -- are bounded by their own request parameters (`max_chars` / `max_results`) and are likewise exempt. A load-bearing consequence: because artifact reads are trusted and unbounded, review phases do not page large artifacts and there is no higher review-phase read ceiling.
