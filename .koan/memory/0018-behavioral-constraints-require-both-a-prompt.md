---
title: Behavioral constraints require both a prompt instruction and a mechanical gate
type: decision
created: '2026-04-16T09:00:52Z'
modified: '2026-06-05T13:06:14Z'
related:
- 0009-permission-fence-impractical-across-llm-backends.md
- 0157-tool-vocabulary-is-restricted-at-toolset.md
---

koan's architecture (documented in `docs/architecture.md`) holds that any behavioral constraint mattering for correctness requires BOTH a prompt instruction and a mechanical gate. Leon recorded the rationale on 2026-04-16: prompt instructions alone are insufficient because LLMs can ignore them without error; mechanical gates alone are insufficient because they produce cryptic "blocked" errors with no context for the model to self-correct. The principle is unchanged, but both of its original exemplars have since been replaced. (1) The call-time permission fence (`check_permission` in the deleted `koan/lib/permissions.py`) was found impractical across LLM backends and removed; tool-vocabulary restriction now happens at toolset-construction time via `compose_toolset` in `koan/tools/tool_policy.py`, so disallowed tools never enter the model's context rather than being blocked at call time. (2) `validate_step_completion()` no longer gates a `koan_complete_step` call -- that tool was removed in the control-loop change on 2026-06-05; the check is now evaluated by the end-of-turn turn-outcome resolver in `koan/agents/loop.py`, which re-injects the same step's guidance when it returns a non-empty error. `validate_step_completion` is a no-op in every current phase, so it stands as the designated enforcement point rather than an active constraint. The prompt-plus-gate principle remains in force via construction-time vocabulary composition and the resolver's completion check.
