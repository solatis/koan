---
title: koan's phase-entry context reset (reset_phase_context) also fires at bootstrap
  and wipes any pending_* state seeded before run_agent_loop
type: lesson
created: '2026-06-30T08:09:59Z'
modified: '2026-06-30T08:09:59Z'
related:
- 0160-context-files-agentsmdclaudemd-are-injected-just.md
- 0261-koan-clears-the-orchestrators-messagehistory-at.md
---

koan's reset_phase_context (koan/tools/handoff_artifacts.py) clears the agent's message_history and pending-injection fields at phase entry, and it runs inside the FIRST _step_phase_handshake_core call -- the bootstrap handshake at the top of run_agent_loop. While adding the phase-boundary reset on 2026-06-30, the project-directory context-file seed (the block in PydanticAIAgent.run that discovers AGENTS.md/CLAUDE.md and appends it to pending_context_files) was initially left in its original position, which runs BEFORE run_agent_loop. The bootstrap reset then cleared that seeded pending_context_files before the first model request consumed it, so the project context file silently stopped being injected on the first request. Root cause: the context reset is a phase-entry choke point that ALSO fires at bootstrap, so any state seeded before the loop is wiped before first use. Correction: the seed was moved out of PydanticAIAgent.run into run_agent_loop, immediately after the bootstrap _step_phase_handshake_core call. Prevention: in the koan agent loop, any pending_context_files / pending_artifacts / similar seeding that must survive the first turn has to run AFTER the bootstrap handshake, not before the loop.
