---
title: 'Artifact persistence: plain markdown files (frontmatter dropped); artifact
  tools are run-dir-scoped wrappers over the built-in file tools'
type: decision
created: '2026-04-26T09:33:27Z'
modified: '2026-06-07T04:01:32Z'
related:
- 0100-artifact-design-doctrine-distinct-lifetimes.md
- 0027-all-state-file-writes-use-atomic-tmp-file.md
---

The koan artifact persistence layer (`koan/artifacts.py`, `koan/tools/koan_tools.py`) stores phase-produced artifacts as markdown files under `~/.koan/runs/<id>/*.md`. Leon removed artifact frontmatter entirely: artifacts are now plain `.md` files with no YAML preamble. `koan/artifacts.py` lost `now_iso`, `split_frontmatter`, `dump_frontmatter`, `compose_artifact`, and `write_artifact_atomic` (plus the `yaml`/`datetime` imports); it keeps only `list_artifacts` (filesystem mtime/size) and the logger. Rationale: nothing outside the artifact tools ever consumed the frontmatter -- the sidebar listing and the `artifact_diff` projection key on path/size/mtime via `list_artifacts`, and the orchestrator's conversation context already holds whatever lifecycle state matters -- so filesystem metadata suffices. This completed an earlier (2026-06-02) narrowing that had removed only the `status` field while keeping `created`/`last_modified`.

The three artifact tools became thin run-dir-scoped wrappers over the built-in file tools in `koan/tools/koan_tools.py`: `artifact_write_core` -> built-in `write_tool`, `artifact_edit_core` -> the anchored `edit_tool`, and `artifact_view_core` was renamed `artifact_read_core` -> `read_tool`. Each wrapper adds only filename validation, a run-dir containment guard (`_resolve_artifact_path`), and (write/edit) the `artifact_diff` event. Two consequences Leon accepted as user decisions during intake: (1) `koan_artifact_view` was renamed `koan_artifact_read` (keeping the `koan_artifact_` prefix; the trusted set is read/write/edit/list); and (2) write atomicity was deliberately given up -- routing `koan_artifact_write` through the plain `write_text`-based `write_tool` drops the old tmp-file + `os.rename` path, accepted as fine for single-writer run-dir artifacts (driver-owned JSON state writes remain atomic via tmp-file + rename, a separate concern). `koan_artifact_edit` also moved off the old `old_string`/`new_string` exact-match signature onto the hash-anchored `edit` signature (`anchor`/`text`/`end_anchor`/`edit_type`), in lockstep with the built-in editor.
