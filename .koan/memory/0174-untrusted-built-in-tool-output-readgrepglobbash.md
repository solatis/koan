---
title: Untrusted built-in tool output (read/grep/glob/bash) is rejected, not truncated,
  above 500 lines or 10 KB
type: decision
created: '2026-06-07T04:01:50Z'
modified: '2026-06-07T04:01:50Z'
related:
- 0163-built-in-tool-output-must-match-the-metrics.md
---

In koan's in-process tool layer (`koan/tools/builtin_tools.py`), a result from the untrusted built-in `read` / `grep` / `glob` / `bash` tools is rejected with an error -- not truncated -- when it exceeds 500 lines or reaches 10 KB (`_MAX_TOOL_OUTPUT_LINES = 500`, `_MAX_TOOL_OUTPUT_BYTES = 10_000`, enforced by `_enforce_output_limits`). Leon chose rejection over truncation in the tool-layer task brief. Rationale: a truncated prefix still costs up to the cap in tokens on every call (a few such calls compound straight into an input-token blowup) and silently misleads the model into believing it saw the whole result; rejection is safe because an untrusted tool always has a narrowing lever, so the error is actionable. The error message must name both the limit and the levers -- `read` `offset`/`limit`, a tighter `grep` pattern or `glob`, a more scoped `bash`. Rejected alternative: keep the prior ~60 KB truncation on `grep`/`glob`/`bash` and add no limit to `read` at all -- rejected because the original incident was precisely an unbounded `read`. The web tools are exempt because they are already bounded by request parameter.
