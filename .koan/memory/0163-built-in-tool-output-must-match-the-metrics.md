---
title: Built-in tool output must match the metrics-parser contract so the projection
  fold can read per-call metrics
type: procedure
created: '2026-06-04T14:16:50Z'
modified: '2026-06-07T04:04:14Z'
related:
- 0156-built-in-agent-tools-reimplemented-as-native-koan.md
- 0162-the-agent-layer-emits-a-fixed-8-type-streamevent.md
- 0175-stateless-hash-anchored-edit-protocol-fnv1a32.md
---

When implementing or changing a koan built-in tool, its textual result must remain parseable by the metrics parsers in `koan/agents/pydantic_ai.py`, because the loop derives each `tool_result` event's `metrics` from the tool's output text and the projection fold renders those metrics per call. The contract by tool family: `read` yields `{lines_read, bytes_read}` -- parsed from the line-numbered read output, which since the hash-anchored edit cutover is the `{lineno}\t{anchor}` + section-sign U+00A7 + `{content}` format rather than plain `cat -n`; that format deliberately preserves the leading `{lineno}\t` prefix the parser keys on (everything after the first tab counts as content), so `lines_read` stays exact while `bytes_read` inflates by the anchor column. `grep` and `glob` yield `{matches, files_matched}` (parsed from the `Found N matches in M files` / `Found N files` summary lines); `ls` yields `{entries, directories}`; and `write`, `edit`, `bash`, and the web tools yield no metrics (`metrics=None`). Violating the contract -- changing a tool's output format without updating its parser -- silently drops that call's metrics: the parser returns `None`, the consumer treats it as no-metrics, and the projection shows nothing for the call rather than erroring. The wrong approach is to treat tool output as free text; its summary lines are a parsed interface.
