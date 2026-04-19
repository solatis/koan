---
title: Directory-as-contract -- task.json over CLI flags for subagent configuration
type: decision
created: '2026-04-16T07:35:24Z'
modified: '2026-04-16T07:35:24Z'
related:
- 0004-file-boundary-invariant-llms-write-markdown.md
---

The subagent configuration mechanism in koan (`koan/subagent.py`, `docs/subagents.md`) was redesigned on 2026-02-10 when Leon replaced a 9-CLI-flag approach with a task.json file convention, later documented as Invariant 6 (Directory-as-contract) in `docs/architecture.md`. The previous design passed task configuration as 9 CLI arguments; Leon replaced it after identifying four problems: (1) the flat flag namespace caused naming collisions (`--koan-role` vs `--koan-scout-role`); (2) role-specific fields mixed with common fields without structure; (3) `--koan-retry-context` needed to carry multi-paragraph summaries exceeding practical CLI limits; (4) after a crash, reconstructing what a subagent had been asked required parsing process arguments from system logs. Leon adopted the convention that the driver would write `task.json` atomically (tmp + `os.rename()`) to the subagent directory before spawn. The subagent discovers its MCP endpoint by reading `mcp_url` from that file. No structured configuration flows through CLI flags, environment variables, or other process-level channels. Leon designated `task.json` as write-once by the parent before spawn and read-once by the parent at agent registration, never modified afterward.
