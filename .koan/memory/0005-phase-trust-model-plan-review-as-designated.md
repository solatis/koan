---
title: Phase trust model -- plan-review as designated adversarial verifier
type: decision
created: '2026-04-16T07:35:13Z'
modified: '2026-04-16T07:35:13Z'
related:
- 0001-persistent-orchestrator-over-per-phase-cli.md
---

The plan workflow's phase trust architecture in koan (`docs/phase-trust.md`, `koan/lib/workflows.py`) was designed around an asymmetric verification model. On 2026-02-10, Leon formalized this as part of the initial koan design: phases in the plan pipeline (intake, plan-spec, execute) were built to trust each other's outputs without re-verification; only plan-review was designated as the adversarial verifier. Leon documented the rationale in `docs/phase-trust.md`: cross-phase re-verification is the "intrinsic self-correction" anti-pattern -- research shows the same LLM re-checking its own prior work is more likely to change correct conclusions to incorrect ones than the reverse. Leon gave plan-review the CRITIC role: it uses the actual codebase as an external tool to check every file path, function name, signature, and type claim in `plan.md` against reality. Leon also decided that plan-review would be advisory only -- it reports findings with severity classification and may suggest looping back to plan-spec for critical or major issues, but it does not modify `plan.md` itself.
