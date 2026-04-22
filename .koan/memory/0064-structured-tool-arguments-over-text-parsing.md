---
title: Structured tool arguments over text parsing -- citations and metadata flow
  through typed schemas, not regex over prose
type: lesson
created: '2026-04-20T08:44:01Z'
modified: '2026-04-20T08:44:01Z'
related:
- 0021-memory-entry-writing-discipline-temporally.md
---

This entry records a corrected anti-pattern during the koan_reflect intake phase in `koan/memory/retrieval/reflect.py` design. On 2026-04-20, the intake orchestrator repeatedly proposed citation validation schemes that parsed `(0003-foo.md)` filename tokens out of the LLM's markdown `answer` text: first as strict filename matching, then as lenient NNNN-prefix matching, then as "either full filename or NNNN prefix". Leon corrected the agent with the exact words "Parsing text is against our conventions, you keep proposing different scenarios where you do this. This is an anti-pattern: citations are structured metadata." Root cause: the agent defaulted to string parsing when the available primitive was a typed tool-call argument. The correct shape was already present -- the `done` tool schema can carry `memory_ids: list[int]` -- but the agent routed metadata through prose and planned regex over the prose instead. The corrected design carries memory_ids as typed integers; the driver resolves them to `{id, title}` pairs server-side using the retrieved set. Rule applied forward: when a tool schema can carry the metadata as typed fields, never synthesize it into natural-language prose and parse it back out. This lesson generalizes beyond reflect -- any LLM-to-driver contract where the LLM must choose an enum, list, or id should use function-call arguments, not prose tokens.
