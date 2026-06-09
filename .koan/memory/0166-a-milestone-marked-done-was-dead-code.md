---
title: 'A milestone marked done was dead code: run_agent_loop existed but nothing
  called it, so the orchestrator ran one turn and exited'
type: lesson
created: '2026-06-04T14:20:07Z'
modified: '2026-06-04T14:20:07Z'
related:
- 0089-proactively-capture-memory-updates-for-discovered.md
- 0153-koan-owns-the-multi-turn-agent-loop-in-process.md
---

A milestone tracking document recorded the multi-turn loop as wired up and done, but the wiring had not happened: `run_agent_loop` existed while the agent's `run()` still took the single-turn path, so nothing ever called the loop and the orchestrator executed exactly one turn before exiting. The "done" marker and the code disagreed. Root cause: the tracking document was advanced to done ahead of the actual wiring, and a run that aborted mid-flight left the divergence in place. Prevention: after a run aborts mid-flight, verify a milestone's "done" claims by reading the code path that implements them -- confirm the new function is actually called -- rather than trusting the tracking document. The tracking doc records intent; only the code records what runs.
