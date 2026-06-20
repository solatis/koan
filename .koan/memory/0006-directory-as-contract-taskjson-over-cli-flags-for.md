---
title: Directory-as-contract -- task.json over CLI flags for subagent configuration
type: decision
created: '2026-04-16T07:35:24Z'
modified: '2026-06-20T00:15:10Z'
related:
- 0004-file-boundary-invariant-llms-write-markdown.md
- 0154-koan-workflow-tools-and-subagents-run-in-process.md
---

The subagent configuration mechanism in koan (`koan/subagent.py`, `docs/subagents.md`) was redesigned on 2026-02-10 when Leon replaced a 9-CLI-flag approach with a task.json file convention, later documented as Invariant 6 (Directory-as-contract) in `docs/architecture.md`. The previous design passed task configuration as 9 CLI arguments; Leon replaced it after identifying four problems: (1) the flat flag namespace caused naming collisions (`--koan-role` vs `--koan-scout-role`); (2) role-specific fields mixed with common fields without structure; (3) `--koan-retry-context` needed to carry multi-paragraph summaries exceeding practical CLI limits; (4) after a crash, reconstructing what a subagent had been asked required parsing process arguments from system logs. Leon adopted the convention that the parent writes `task.json` atomically (tmp + `os.rename()`) to the subagent directory before spawn, and the subagent reads its configuration -- role, `run_dir`, and its task-specific fields -- from that file. No structured configuration flows through CLI flags, environment variables, or other process-level channels. Leon designated `task.json` as write-once by the parent before spawn and read-once by the parent at agent registration, never modified afterward.

The convention outlived the transport it was born with. When koan moved to the in-process PydanticAI agent layer in June 2026 the HTTP MCP transport was deleted, so the former `mcp_url` field in `task.json` is gone: in-process subagents (spawned as asyncio tasks) receive their tools from the composed PydanticAI toolset rather than by connecting to an MCP endpoint, and `task.json` remains the configuration contract. The orchestrator's own `task.json` additionally carries `workflow_history` (the append-only list of workflow entries); executor and scout task files do not.
