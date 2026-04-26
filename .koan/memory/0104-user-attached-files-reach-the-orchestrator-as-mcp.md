---
title: User-attached files reach the orchestrator as MCP content blocks, not as text-injected
  file paths
type: decision
created: '2026-04-24T16:39:03Z'
modified: '2026-04-24T16:39:03Z'
---

This entry documents the file-delivery choice for user-attached files in the koan workflow engine (`koan/web/uploads.py`, `koan/web/mcp_endpoint.py`). On 2026-04-24, during intake for the file-attachment initiative, Leon decided that uploaded files reach the orchestrator as MCP `ImageContent` and `EmbeddedResource` content blocks (via `fastmcp.utilities.types.Image` and `File` wrappers), interleaved into the same `CallToolResult` that returns the user's text. Leon's stated rationale: content is provided directly into the model's context where it was uploaded, avoiding an extra tool call for the orchestrator to open the file. Alternative rejected: inject absolute file paths into the user message text and let the orchestrator open them with its Read tool; Leon rejected this because it adds a tool-call round-trip and separates file content from the text it accompanies. Scope constraint for the initiative: Claude only. Non-Claude runners (codex, gemini) receive a single `TextContent` notice listing the attached filenames instead of real file blocks, because koan does not configure directory-scope or file-access permissions for those runners beyond their yolo-bypass flags. The audit-log manifest attached to the `tool_completed` event (shape `{upload_id, filename, size, content_type, path}` per entry) is populated for every runner regardless of delivery capability. The decision lands in `koan/web/uploads.py:upload_ids_to_blocks` as the single primitive that resolves upload IDs to content blocks with the `runner_type == "claude"` gate centralizing runner capability.
