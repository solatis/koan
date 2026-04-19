---
title: 'Curation phase: 3-step layout collapsed to 2 to prevent meaty-step skip failure'
type: lesson
created: '2026-04-16T08:34:15Z'
modified: '2026-04-16T08:34:15Z'
related:
- 0002-step-first-workflow-pattern-boot-prompt-is.md
---

The curation phase module in koan (`koan/phases/curation.py`) was originally implemented as a 3-step workflow with step names "Survey", "Curate", and "Finalize/Reporting". During a curation run whose output Leon reviewed in screenshots, the orchestrator was observed to confuse "Survey" with intake-style exploration and then reach "phase complete" without ever calling `koan_memorize` -- a failure mode where the curation phase ended with zero memory writes. Leon identified two root causes: (1) the name "Survey" triggered intake-like behavior; (2) there was no per-step structural framing (no workflow_shape, goal, or tools list) visible at the moment the LLM decided whether to advance. On 2026-04-16, Leon approved a redesign that collapsed the 3 steps to 2 (Inventory and Memorize), named after their primary tool effects (`koan_memory_status` and `koan_memorize`) to make step-skipping visible, and added `<workflow_shape>`, `<goal>`, and `<tools_this_step>` XML blocks to every step, re-injected at each `koan_complete_step` call so the phase structure is visible at the moment of use rather than only at step 1.
