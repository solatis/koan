---
title: Driver-managed YAML frontmatter on artifacts (status / created / last_modified)
  + Draft / Approved / In-Progress / Final taxonomy + koan_artifact_write tool
type: decision
created: '2026-04-26T09:33:27Z'
modified: '2026-04-26T09:33:27Z'
related:
- 0100-artifact-design-doctrine-distinct-lifetimes.md
- 0101-intake-produces-briefmd-as-a-frozen-handoff.md
---

The koan artifact persistence layer (`koan/artifacts.py`, `koan/web/mcp_endpoint.py`) gained driver-managed YAML frontmatter on 2026-04-25 during M1 of the unified-artifact-flow initiative. Leon endorsed via plan-spec / execute / exec-review for M1 (clean execution, 698 tests passed). The change: every artifact written to `~/.koan/runs/<id>/*.md` carries a YAML frontmatter preamble with three fields in fixed insertion order -- `status`, `created`, `last_modified`. Fields are driver-maintained and LLM-invisible: `koan_artifact_view` strips frontmatter via `split_frontmatter()` before returning body to the LLM; `list_artifacts()` exposes `status` per file via `read_artifact_status()` (4 KiB-bounded read). The status taxonomy is `STATUS_VALUES = ("Draft", "Approved", "In-Progress", "Final")` defined in `koan/artifacts.py`; first-write defaults to `In-Progress`; producers set `Final` explicitly for frozen artifacts (intake calls `koan_artifact_write(filename="brief.md", content=BODY, status="Final")` per memory entry 101). A new MCP write tool `koan_artifact_write(filename, content, status?)` was added at `koan/web/mcp_endpoint.py:2059-2124` as a non-blocking sibling of `koan_artifact_propose`; both shared the `write_artifact_atomic(target, body, status)` helper preserving `created` across rewrites. M5 deleted `koan_artifact_propose` entirely on 2026-04-26 once all production callers migrated to `koan_artifact_write`. PyYAML usage mirrors `koan/memory/{writer.py:62, parser.py:50}`: `yaml.safe_dump(meta, default_flow_style=False, sort_keys=False)` and `yaml.safe_load(text)`. Frontmatter format follows YAML 1.2 frontmatter convention (`---`-delimited block at file head); parseable by any standard markdown reader; malformed frontmatter falls back to `(None, original_text)` with logged warning. `docs/artifacts.md` (113 lines) codifies the lifetime taxonomy (frozen / additive-forward / disposable per memory entry 100) and per-artifact lifecycle table.
