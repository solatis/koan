---
title: Blocking MCP tool handlers that park on per-run asyncio futures must guard
  against reentry
type: procedure
created: '2026-04-21T13:19:51Z'
modified: '2026-04-21T13:19:51Z'
related:
- 0033-new-mcp-tool-handlers-in-koanwebmcpendpointpy.md
---

This entry records a procedural rule for MCP tool handlers in `koan/web/mcp_endpoint.py` that use a blocking `asyncio.Future` stored on `AppState.interactions`. On 2026-04-21, Leon established during plan-review of the `koan_artifact_propose` implementation that any such handler must guard against reentry: before creating a new future and parking on it, the handler reads `existing = app_state.interactions.<future_field>`, checks `if existing is not None and not existing.done()`, and raises `ToolError(json.dumps({"error": "<domain>_already_pending", "message": "..."}))` on reentry rather than silently overwriting. Root cause analyzed at the time: if a prior call were still awaiting resolution when a second call arrived (possible under future refactors or subtle control-flow bugs), reassignment would drop the prior caller's resolution handle and the `await` would park forever. The guard was added to `koan_artifact_propose` on 2026-04-21. The same structural gap is present in `koan_yield`'s `yield_future` handling as of 2026-04-21 and was left unguarded within the scope of that change -- documented here as a concrete instance to which the rule applies.
