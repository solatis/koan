---
title: Persistent orchestrator over per-phase CLI spawning
type: decision
created: '2026-04-16T07:13:41Z'
modified: '2026-06-05T01:55:03Z'
related:
- 0153-koan-owns-the-multi-turn-agent-loop-in-process.md
---

koan runs the entire workflow as a single long-lived orchestrator rather than spawning a fresh process per phase. Leon's rationale: per-phase spawning caused compounding context loss -- each new process re-derived what the previous had explored -- and a separate `workflow-orchestrator` subagent spawned just to present the next-phase decision was "a process-boot just to ask a question." The persistent orchestrator holds one continuous reasoning chain across phases, and `koan_set_phase` is the phase-transition tool. One alternative was rejected at the time and has since been adopted: driving the conversation directly against the provider API (rather than through a runner/subprocess abstraction) was first rejected for fear of losing model selection, output streaming, and thinking-mode handling -- but koan now owns exactly that in-process loop against provider APIs, having reproduced those capabilities natively (StreamEvent streaming, ModelSpec model selection, per-provider thinking via map_thinking). The other rejected alternative still stands: injecting context into fresh per-phase processes does not provide a persistent reasoning chain. The persistence decision is unchanged; only the loop's implementation moved from a spawned CLI subprocess to an in-process provider-API loop.
