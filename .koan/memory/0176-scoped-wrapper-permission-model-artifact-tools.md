---
title: 'Scoped-wrapper permission model: artifact tools confine the orchestrator''s
  file writes to its run directory'
type: decision
created: '2026-06-07T04:04:02Z'
modified: '2026-06-07T04:04:02Z'
related:
- 0157-tool-vocabulary-is-restricted-at-toolset.md
- 0173-three-class-tool-trust-taxonomy-untrusted-built.md
- 0112-driver-managed-yaml-frontmatter-on-artifacts.md
---

koan's permission model for filesystem WRITES rests on the artifact tools being thin run-dir-scoped wrappers over the built-in file tools (`koan/tools/koan_tools.py`). The orchestrator (a planning role) can read anything via the raw built-in `read`, but it can write only run-dir artifacts, and only through `koan_artifact_write` / `koan_artifact_edit`, which validate the filename and enforce a run-dir containment guard (`_resolve_artifact_path`) before delegating to the built-in `write_tool` / `edit_tool`. Leon's rationale: the wrappers exist to LIMIT file access -- a planning role gets a file interface confined to its own `~/.koan/runs/<id>/` directory -- while reusing the built-in read/write/edit semantics (including the hash-anchored edit) rather than reimplementing them. This is a different mechanism from koan's other permission control, which restricts the tool VOCABULARY per (role, phase) at toolset-construction time via `compose_toolset` in `koan/tools/tool_policy.py`: vocabulary control decides which tools exist for a role; the scoped wrappers decide how far the artifact-write tools can reach on the filesystem. The orchestrator's role permissions accordingly grant raw `read` but withhold raw `write`/`edit`, leaving the run-dir-scoped artifact wrappers as its only write path.
