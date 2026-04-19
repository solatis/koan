---
title: 'New MCP tool handlers in koan/web/mcp_endpoint.py must use try/finally with
  result_str: str | None = None'
type: procedure
created: '2026-04-16T13:31:07Z'
modified: '2026-04-16T13:31:07Z'
---

When adding any new `@mcp.tool(name="...")` handler to `koan/web/mcp_endpoint.py`, follow the established lifecycle pattern. On 2026-04-16, the plan-review phase caught a deviation in the initial `koan_search` draft: the draft called `end_tool_call` inside both the except block and after the try/except, and placed `_drain_and_append_steering` outside the try block. The user-approved correction, verified against `koan_memorize` at line 906, `koan_forget` at line 966, and `koan_memory_status` at line 1001, uses this structure:

```
result_str: str | None = None
try:
    # ... do work ...
    result_str = json.dumps(...)
    result_str = _drain_and_append_steering(result_str, agent)
    return result_str
except SpecificError as e:
    raise ToolError(json.dumps({"error": "...", "message": str(e)}))
finally:
    end_tool_call(agent, call_id, tool_name, result_str)
```

`result_str` initialized to `None` before the try block ensures `end_tool_call` receives `None` when an exception occurs before the result is assembled. `_drain_and_append_steering` executes inside the try block, not after it. The decorator uses `@mcp.tool(name="koan_...")` with an explicit name string, not the bare `@mcp.tool()` form.
