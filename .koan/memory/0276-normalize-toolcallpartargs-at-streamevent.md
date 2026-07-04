---
title: Normalize ToolCallPart.args at StreamEvent construction boundary in koan/agents/loop.py,
  not at downstream consumers
type: decision
created: '2026-07-03T07:19:04Z'
modified: '2026-07-03T07:19:04Z'
related:
- 0078-pydantic-ai-integration-traps-in-koan-agent-loops.md
---

koan agent loop (`koan/agents/loop.py`) — Leon decided to normalize `ToolCallPart.args` at the `StreamEvent` construction boundary rather than adding defensive guards at every downstream consumer. The `StreamEvent.tool_args` field is typed `dict | None` in `koan/agents/events.py` — the value must match the type annotation. Normalizing at construction enforces this contract for all downstream consumers: the projection fold (`koan/projections.py`), the event builders (`koan/events.py`), and the subagent layer (`koan/subagent.py`).

Rationale: a type annotation is a contract. When the upstream source (`ToolCallPart.args` from pydantic-ai) can produce a `str` but the field is typed `dict | None`, the normalization belongs at the point where the value crosses the type boundary — not scattered across every consumer that calls `.get()` on it. Boundary-only normalization keeps the fix localized and makes the type annotation truthful.

Alternatives rejected:
- Fold-only defensive guards in `koan/projections.py` — would prevent the crash but leave the `StreamEvent.tool_args` type annotation misleading. Every future consumer of `tool_args` would need to independently discover and guard against the `str` case.
- Builder-level normalization in `koan/events.py` (`build_tool_request` / `build_tool_input_delta`) — builders are pass-through by design; adding normalization there is less visible and splits the concern across two modules.
- Defense-in-depth at both boundary and consumers — adds maintenance burden without benefit when the boundary is enforced. Leon explicitly rejected this option.

The normalization follows the existing pattern at `koan/projections.py:1531-1535` (the `koan_reflect` args path): `isinstance` check → `json.loads` → fallback `{"raw": raw_args}` on `JSONDecodeError` or `TypeError`. Decision surfaced during investigation of an `AttributeError` crash in the projection fold on 2026-07-03, when Ollama/DeepSeek sent tool call arguments as a JSON string.
