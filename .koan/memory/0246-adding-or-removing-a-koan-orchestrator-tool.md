---
title: Adding or removing a koan orchestrator tool requires updating the KOAN_MCP_TOOLS
  vocabulary in koan/agents/events.py (guarded by test_vocabulary_drift.py)
type: procedure
created: '2026-06-22T23:56:54Z'
modified: '2026-06-22T23:56:54Z'
related:
- 0243-koan-execution-unbundled-into-koanrequestexecutor.md
---

koan maintains a canonical frozenset of tool NAMES, `KOAN_MCP_TOOLS`, in `koan/agents/events.py`, guarded by `tests/test_vocabulary_drift.py` -- this is separate from the tool registration in `build_koan_toolset` (`koan/tools/koan_tools.py`) and the per-(role, phase) allowlist in `koan/tools/tool_policy.py`. When the `koan_request_executor` tool was added to koan, registering it in the toolset builder and `tool_policy.py` was insufficient: `tests/test_vocabulary_drift.py` failed until the new tool name was also added to `KOAN_MCP_TOOLS`. Procedure: when adding or removing an orchestrator tool, update three places together -- the toolset builder, `tool_policy.py` (the role/phase allowlist), and `KOAN_MCP_TOOLS` in `koan/agents/events.py`. Updating only the toolset and the policy leaves the vocabulary out of sync and breaks `tests/test_vocabulary_drift.py`.
