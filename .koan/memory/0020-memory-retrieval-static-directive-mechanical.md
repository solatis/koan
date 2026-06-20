---
title: 'Memory retrieval: static-directive mechanical injection handles unknown unknowns;
  agent tools handle known unknowns'
type: decision
created: '2026-04-16T09:01:12Z'
modified: '2026-06-20T03:25:38Z'
related:
- 0012-koan-is-dog-fooded-on-its-own-development-meta.md
- 0063-koanreflect-synthesis-tool-single-conversation.md
---

koan's memory system (documented in `docs/memory-system.md`) implements two retrieval mechanisms under an asymmetric design Leon established. Mechanical context injection runs automatically at phase boundaries using static retrieval directives authored by the workflow designer; agent-invoked tools are called on-demand during reasoning. The two solve different problems. Mechanical injection handles unknown unknowns -- knowledge the agent does not know to search for (a procedure about credential handling, a lesson about a past failure); since the agent cannot formulate a query for what it does not know exists, the injection must run without relying on agent reasoning. Agent-invoked tools handle known unknowns -- gaps the agent recognizes during reasoning and can formulate targeted queries for. Leon explicitly rejected LLM-generated retrieval directives (having the orchestrator generate directives at runtime) because such directives would produce queries biased toward what the orchestrator already knows, collapsing both mechanisms into one and leaving unknown unknowns uncovered. The static directive encodes structural knowledge about each phase type's typical needs, independent of any particular agent's reasoning state. The mechanical injection path lives in `koan/tools/koan_tools.py` -- `_compute_memory_injection_core`, composed into the phase handshake `_step_phase_handshake_core` and driven by the in-process agent loop in `koan/agents/loop.py`; two agent-invoked in-process tools are exposed -- `koan_search` (single-query hybrid retrieval) and `koan_reflect` (multi-turn synthesis loop).
