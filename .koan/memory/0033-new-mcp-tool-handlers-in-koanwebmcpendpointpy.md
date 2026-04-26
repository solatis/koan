---
title: 'New MCP tool handlers in koan/web/mcp_endpoint.py must use try/finally with
  result_blocks: list[ContentBlock] | None = None'
type: procedure
created: '2026-04-16T13:31:07Z'
modified: '2026-04-24T16:38:52Z'
---

When adding any new `@mcp.tool(name="...")` handler to `koan/web/mcp_endpoint.py`, follow the established lifecycle pattern. On 2026-04-16, the plan-review phase caught a deviation in the initial `koan_search` draft that called `end_tool_call` inside both the except block and after the try/except, and placed `_drain_and_append_steering` outside the try block. On 2026-04-24, during the file-attachment initiative (M2), Leon changed every primary-agent tool handler from returning `str` to returning `list[ContentBlock]` so the tool surface could carry mixed text and attachment content blocks. The current structure, verified across the 20 `@mcp.tool` closures in `koan/web/mcp_endpoint.py`:

```
result_blocks: list[ContentBlock] | None = None
steer_manifest: list[dict] = []
try:
    # ... do work ...
    result_blocks = [_text_block(assembled_text)]
    result_blocks, steer_manifest = _drain_and_append_steering(result_blocks, agent)
    return result_blocks
except SpecificError as e:
    raise ToolError(json.dumps({"error": "...", "message": str(e)}))
finally:
    end_tool_call(agent, call_id, tool_name, result_blocks, steer_manifest or None)
```

`result_blocks` initialized to `None` before the try block ensures `end_tool_call` receives `None` when an exception occurs before the result is assembled. `_text_block(s)` at `koan/web/mcp_endpoint.py:82` is the single wrap helper that converts an assembled string into a `TextContent` block. `_drain_and_append_steering` returns `(blocks, manifest)` as a tuple; the manifest aggregates attachment metadata across the tool's own emissions plus drained steering messages and is passed to `end_tool_call` as the `attachments` argument. The decorator uses `@mcp.tool(name="koan_...")` with an explicit name string, not the bare `@mcp.tool()` form. Single-`TextContent` returns are wire-identical to plain-string returns through fastmcp; the list shape is the protocol-stable superset that lets non-text content (file / image blocks) sit alongside text.
