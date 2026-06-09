---
title: 'Pydantic-AI integration traps in koan agent loops: output_type=str accepts
  prose as termination; agent.iter() swallows tool-handler exceptions'
type: lesson
created: '2026-04-22T09:38:12Z'
modified: '2026-04-27T09:02:17Z'
related:
- 0064-structured-tool-arguments-over-text-parsing.md
- 0063-koanreflect-synthesis-tool-single-conversation.md
---

This entry documents two pydantic-ai library behaviors that bit koan's multi-turn agent-loop implementations (currently the `koan_reflect` synthesis tool; any future reflective-loop tool in koan will hit the same traps). The knowledge was distilled on 2026-04-22 after Leon root-caused an `IterationCapExceeded` failure in `koan_reflect`'s pydantic-ai loop and iterated through two successive fixes.

Trap 1 -- `output_type=str` treats any plain-text model response as a valid agent termination. Pydantic-ai's default output contract accepts prose as the final result: the model runs its searches, writes its briefing as a plain-text response, and pydantic-ai exits the `async for node in run` loop cleanly without ever invoking the designated completion tool. The old raw google-genai loop in koan had an explicit text-only detection path that nudged the model back to tool use; pydantic-ai omits that nudge. The initial instinct -- simply drop `output_type=str` -- is insufficient, because pydantic-ai's default still allows text termination. The fix Leon adopted on 2026-04-22 is to close the text escape hatch explicitly: pass `output_type=TextOutput(_reject_text)` where `_reject_text` raises `ModelRetry` on every text output, forcing the model to call the designated completion tool instead of producing prose. Without this, a model update that shifts default behaviour toward direct text (as happened with Gemini in April 2026) silently breaks the loop.

Trap 2 -- `agent.iter()` does not propagate exceptions from tool handlers to user code. The old raw google-genai loop in koan used a sentinel `_DoneSignal` exception raised from the `done` tool handler and caught around the loop; the loop exited via the exception path. In pydantic-ai, tool execution happens inside `CallToolsNode` and exceptions from tool handlers are caught internally -- they never reach an `except _DoneSignal:` wrapping `async for node in run`. The fix Leon adopted on 2026-04-22: the `done` tool handler stores its structured result (citations, final briefing text, etc.) on the shared `deps` object as `_DoneResult` and returns normally; the outer loop checks `deps.done_result` after each node and breaks when it is set. Exception-based termination does not work in pydantic-ai; deps-based result handoff does.

Leon noted on 2026-04-22 that with both traps known upfront, building a new pydantic-ai agent loop in koan is roughly a 5-minute edit; without them it takes a ~20-minute investigation because trap 2 only manifests after trap 1 is fixed. The underlying project invariant reaffirmed on the same day: koan accepts structured agent output via tool calls with typed arguments, not via parsing the model's last message.
