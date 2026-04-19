---
title: Persistent orchestrator over per-phase CLI spawning
type: decision
created: '2026-04-16T07:13:41Z'
modified: '2026-04-16T07:13:41Z'
---

This entry documents the orchestrator spawn architecture decision in koan's workflow engine (`koan/driver.py`). On 2026-04-02, Leon redesigned the system to replace per-phase CLI process spawning with a single long-lived orchestrator process running the entire workflow in one continuous session. Previously, each planning phase spawned a fresh `claude`, `codex`, or `gemini` CLI process; a separate `workflow-orchestrator` subagent was then spawned to present the user with a phase-selection decision after each phase completed. Leon's rationale: per-phase spawning caused compounding context loss (each new process re-derived what the previous had explored), and the workflow-orchestrator role was architecturally wasteful -- "a process-boot just to ask a question." Two alternatives were explicitly rejected: (1) API-based conversation (driver calling the LLM API directly) -- would have bypassed the runner abstraction handling model selection, MCP config, output streaming, and thinking mode; (2) context injection into fresh processes per phase -- cheaper but fails to provide a persistent reasoning chain and does not eliminate the workflow-orchestrator overhead. The redesign landed in `koan/driver.py` as a single `spawn_subagent()` call awaiting the orchestrator's exit, and added `koan_set_phase` as the new phase-transition tool replacing the two-tool `koan_propose_workflow` / `koan_set_next_phase` dance.
