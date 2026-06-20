---
title: plan producer and reviewer require Implementation-step-level docstring directives
  for newly-added or modified functions
type: decision
created: '2026-04-27T16:06:42Z'
modified: '2026-06-20T04:28:24Z'
related:
- 0038-cross-reference-repetition-in-prompt-instructions.md
---

koan requires Implementation-step-level docstring directives for newly-added or modified functions, a docstring-discipline doctrine Leon added. Requirement: function documentation is required, and functions without docstrings should be flagged. Scope: the directive applies to newly-added OR modified functions (not new-only, and not every function in a file the plan touches); it is presence-only, with format following the surrounding file convention (PEP 257 / Google / NumPy / JSDoc not mandated). Implementation: the producer plan phase carries a documentation-discipline section requiring that any step adding or modifying a function direct the executor to write or update that function's docstring; the mechanical reviewer's PLAN_REVIEWER charter (`koan/phases/reviewer.py`, spawned on `koan_artifact_write` of a plan) flags any newly-added or modified function whose plan Implementation step lacks a docstring directive. Rejected alternatives: only newly-added functions (misses changed signatures/behavior); every function in any touched file (forces unrelated cleanup); mandating a specific docstring style (no project-wide style is recorded).
