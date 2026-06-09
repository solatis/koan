---
title: plan-spec and plan-review require Implementation-step-level docstring directives
  for newly-added or modified functions
type: decision
created: '2026-04-27T16:06:42Z'
modified: '2026-04-27T16:06:42Z'
related:
- 0038-cross-reference-repetition-in-prompt-instructions.md
---

On 2026-04-27, Leon added an explicit docstring-discipline doctrine to the plan-spec and plan-review phase modules (`koan/phases/plan_spec.py`, `koan/phases/plan_review.py`). Leon's stated requirement: "I would like to make it explicit in the plan-spec and plan-review phase, that function documentation is required. Functions without docstrings should be flagged." Scope: the docstring directive applies to newly-added OR modified functions (not new-only, and not all functions in any file the plan touches); the requirement is presence-only, with format following the surrounding file convention (PEP 257 / Google / NumPy / JSDoc not mandated). Implementation: plan-spec's `PHASE_ROLE_CONTEXT` gained a `## Documentation discipline` section and a matching MUST bullet in `## Strict rules`; the step-2 `### Implementation steps` plan-structure block gained a `**Documentation**` bullet stating that any step adding or modifying a function MUST direct the executor to write or update that function's docstring. Plan-review's evaluation dimensions gained a `**Docstring discipline**` dimension that flags any newly-added or modified function whose Implementation step lacks a docstring directive; the strict-rules block was updated with a corresponding MUST-flag rule. Rejected alternatives: (a) only newly-added functions -- rejected because it misses functions whose signatures or behavior change; (b) every function in any file the plan touches -- rejected because it forces unrelated documentation cleanup; (c) specifying PEP 257 / Google / JSDoc explicitly -- rejected because no project-wide docstring style had been recorded in memory and mandating one would conflict with files using a different convention. The doctrine was applied with cross-reference repetition: each rule appears in `PHASE_ROLE_CONTEXT` and again in the relevant step-2 block of both modules.
