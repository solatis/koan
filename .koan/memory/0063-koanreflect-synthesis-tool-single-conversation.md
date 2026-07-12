---
title: "cite(memory_ids) replaces done(answer, memory_ids) in koan_reflect \u2014\
  \ prose moves from tool channel to terminal text output"
type: decision
created: '2026-04-20T08:43:52Z'
modified: '2026-07-04T15:21:58Z'
related:
- 0064-structured-tool-arguments-over-text-parsing.md
- 0078-pydantic-ai-integration-traps-in-koan-agent-loops.md
---

The `koan_reflect` synthesis tool in `koan/memory/retrieval/reflect.py` — Leon replaced the internal `done(answer: str, memory_ids: list[int])` tool with `cite(memory_ids: list[int])`. The model now calls `cite` with backing entry ids, then writes the briefing as terminal text output, which ends the loop via PydanticAI's native End condition. The `_resolve_citations` function and its hallucination guard (validate ids against the `retrieved` dict, drop and log unknowns) are retained unchanged.

Rationale: a 300–500 token markdown briefing inside a JSON string argument inherits per-model structural-output reliability variance — the STED benchmark shows structural consistency varies substantially across models and temperatures — and the reflect loop runs on whatever model the user assigned to the `standard` tier. Keeping prose out of the tool channel and in the terminal text output avoids this variance.

Alternatives rejected: keeping `done(answer, memory_ids)` with prose in the tool channel — structural-output reliability varies by model, and the streaming pipeline (`text` → `reflect_delta` → `result.answer`) was structurally dead because `TextOutput(_reject_text)` rejected every text emission.

The citation-selection guidance (an entry backs a claim only if removing it would force dropping the claim; citing seen-but-unused entries is the primary failure mode) carries over verbatim into the `cite` tool docstring and `SYSTEM_PROMPT`. The `SYSTEM_PROMPT` workflow steps 3–4 and Termination section were rewritten for the new sequence: searches → cite → briefing text → end.

The original architecture — single-conversation LLM tool-calling loop, driver-resolved citations, `MAX_ITERATIONS = 10` cap with fail-fast on exhaustion — is unchanged. The four alternatives Leon rejected on 2026-04-20 (separately orchestrated prompts, cheap-tier model, best-effort partial briefing on cap, sibling Gemini wrapper) remain rejected. The model-resolution path (originally module-local helpers, then per-run `MemoryModels.reflect_llm` on 2026-06-12, then standard-tier resolution on 2026-07-01) is unchanged by this decision.

Decision surfaced when the `TextOutput(_reject_text)` pattern in `_build_agent` was identified as the root cause of the dead streaming pipeline — the reject pattern was necessary when prose lived in the `done` tool argument, and removing prose from the tool channel eliminated the need for the reject pattern.
