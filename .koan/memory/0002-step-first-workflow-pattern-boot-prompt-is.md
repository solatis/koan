---
title: Step-first workflow pattern -- boot prompt is exactly one sentence
type: decision
created: '2026-04-16T07:13:50Z'
modified: '2026-04-16T07:13:50Z'
---

The step-first workflow pattern governs how all LLM subagent CLI processes in koan receive task instructions. On 2026-02-10, Leon established this as a load-bearing architectural invariant in the koan initial design (documented in `docs/architecture.md` as Invariant 2 and enforced in `koan/web/mcp_endpoint.py`). The rule: every subagent's boot prompt is exactly one sentence -- role identity plus "Call koan_complete_step to receive your instructions." Task details, phase guidance, and tool lists arrive exclusively as the return value of the first `koan_complete_step` MCP call. The pattern was motivated by a failure mode observed with haiku-class (weaker) models: complex task instructions in the boot prompt caused these models to produce text output on the first turn and exit without ever entering the tool-calling loop. Three reinforcement mechanisms make the pattern robust across model capability levels: primacy (boot prompt is the LLM's very first message), recency (`format_step()` in `koan/phases/format_step.py` always appends "WHEN DONE: Call koan_complete_step..." last), and muscle memory (by step 2 the LLM has called the tool multiple times, locking in the pattern).
