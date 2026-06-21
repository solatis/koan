---
title: Artifact and transition tool permission failures return a recoverable {ok:false}
  envelope, gated by a per-step (phase, step) catalog with an out_of_step code
type: decision
created: '2026-06-21T11:32:37Z'
modified: '2026-06-21T11:32:37Z'
related:
- 0026-recoverable-vs-unrecoverable-error-classification.md
- 0176-scoped-wrapper-permission-model-artifact-tools.md
- 0009-permission-fence-impractical-across-llm-backends.md
- 0157-tool-vocabulary-is-restricted-at-toolset.md
- 0100-artifact-design-doctrine-distinct-lifetimes.md
---

koan's artifact-mutation tools (`koan_artifact_write`, `koan_artifact_edit`) and workflow-transition tools (`apply_set_phase`, `apply_set_workflow` in `koan/tools/koan_tools.py`) gate calls through a per-step, recoverable permission model Leon adopted in 2026-06. It combines two changes. (1) Per-step catalog: `ArtifactRegistryEntry` in `koan/tools/artifact_registry.py` carries `create_steps` and `edit_steps` -- sets of `(phase, step_name)` pairs stating exactly when each artifact family may be created or edited (for example, brief.md only at intake's Summarize step; milestones.md created at the milestone Write step but also editable at execute's Assess step) -- with `origin_phases` derived from `create_steps`. The tool core resolves the current step name from the phase module's `STEP_NAMES` and passes it to `validate_write` / `validate_edit`, which reject a wrongly-timed call with a new `out_of_step` code whose `allowed` field names the legal (phase, step) positions so the model can self-correct. (2) Uniform recoverable return: every agent-correctable validation failure across all four tools is RETURNED to the model as `{"ok": false, "error": {reason, message, allowed, suggested_name}}` rather than raised; only genuine infrastructure faults (no run directory, a path escaping the run directory, an underlying write/edit failure) and internal-config faults still raise. Review sidecars (`.review.md`) are exempt from per-step gating, and the per-step check is fail-open when the step name cannot be resolved.

Rationale: the tools previously raised `ValueError` for correctable failures, and because pydantic-ai does not catch arbitrary tool exceptions, one recoverable mistake -- a second `koan_artifact_write` to an existing draft -- propagated out of the loop and crashed the entire workflow; the recoverable-return contract koan already had for tool-call failures had simply not been applied to these surfaces. Returning a structured envelope keeps the run alive and lets the model retry unboundedly. Alternatives rejected: pydantic-ai's `ModelRetry` (budgeted -- default `retries=1` -- and exhaustion raises `UnexpectedModelBehavior`, which crashes the run, defeating unbounded recovery); expressing per-step capability by adding or removing tools per step (would change the cached tool-definition prefix at every step boundary and destroy prompt caching, so enforcement must be a runtime call-validator, never tool-hiding); and bolting the step check onto the pre-existing scattered checks instead of consolidating the catalog as the single source of truth. Unbounded recovery is a property of the gate; the run's per-turn request budget remains the final backstop against a pathologically non-converging model.
