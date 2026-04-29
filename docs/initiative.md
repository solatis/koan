# Initiative Workflow

The initiative workflow is the most complete preset koan offers. It runs the
full sequence of design-and-delivery phases for substantial undertakings whose
ceremony the leaner `plan` and `milestones` workflows cannot carry. The
workflow is structurally a superset of `milestones`: it adds two design-heavy
phases above milestone decomposition (`core-flows` and `tech-plan-spec` plus
its review), reuses `milestone-spec`, `milestone-review`, `plan-spec`,
`plan-review`, `execute`, `exec-review`, and `curation` unchanged from the
existing milestones workflow, and inherits the same loop semantics.

> Parent doc: [architecture.md](./architecture.md)
> Phase reference: [workflow-phases.md](./workflow-phases.md)
> Diagram contracts: [visualization-system.md](./visualization-system.md)
> Related: [phase-trust.md](./phase-trust.md), [milestones.md](./milestones.md), [artifacts.md](./artifacts.md)

## What the initiative workflow is for

An initiative is a substantial undertaking that spans multiple milestones,
crosses architectural boundaries, and warrants a shared, persistent record of
the design decisions made along the way. The defining property is the
presence of architectural decisions that cross multiple milestones. When
milestones share design assumptions about data shapes, integration seams,
naming conventions, and error-handling strategies, those assumptions need a
load-bearing artifact that is decided once, validated by the human, and then
trusted by every milestone that follows. The `tech-plan.md` artifact carries
that load.

The hierarchy among the three delivery workflows is `plan` < `milestones` <
`initiative`. The `plan` workflow handles a focused change with no
multi-milestone decomposition. The `milestones` workflow handles a
multi-milestone change whose architecture is implicit in the existing
codebase. The `initiative` workflow handles a multi-milestone change whose
architecture is itself a design question, plus its externally-visible
behavior is also worth describing as a shared artifact rather than carried
in dialogue alone.

The cost of running `initiative` when one of the leaner presets would have
done is concrete: the orchestrator will spend tokens producing a `core-flows.md`
and a `tech-plan.md` whose contents restate what was already obvious. The
symptom of running the wrong preset is a tech-plan whose decisions are
trivially derivable from the brief without any architectural reasoning. When
that happens, downgrading to `milestones` is the right move.

## Phase sequence

The full sequence is `intake -> core-flows -> tech-plan-spec -> tech-plan-review
-> milestone-spec -> milestone-review -> plan-spec -> plan-review -> execute ->
exec-review`, with the `plan-spec -> plan-review -> execute -> exec-review` loop
repeating once per milestone, and `curation` as the terminal phase after the
last milestone is `[done]`.

The phases above milestone-spec are what distinguish initiative from
milestones. Below milestone-spec, the workflow is identical to the existing
milestones workflow and reuses the same phase modules with the same
guidance.

The `core-flows` phase is included in the standard initiative path but is
yield-skippable. When the operational behavior of the system is already
settled in the dialogue between the user and the agent during intake, the
user can yield from intake directly to `tech-plan-spec` and the workflow
proceeds without writing `core-flows.md`. The `tech-plan-spec` and
`tech-plan-review` phases are not skippable. If architectural reasoning is
not warranted, the right preset is `milestones`, not initiative without
tech-plan.

The `frame` phase is not part of the initiative path. It is reachable from
any yield boundary in any workflow as an escape hatch when the user
discovers mid-workflow that they need to step back and explore. Frame lives
in the standalone `discovery` workflow and is described in
`workflow-phases.md`.

## What initiative adds beyond milestones

The first addition is `core-flows`, a single-phase band (no review pair)
whose responsibility is to produce `core-flows.md`. The artifact is
visualization-first by construction: its load-bearing content is mermaid
sequence diagrams over the relevant actors, plus step narratives that
describe triggers, sequenced steps, and exit conditions. The artifact is
constrained to the operational level -- no file paths, no component names, no
implementation detail. The diagram contracts (one `sequenceDiagram` per flow,
sized per the suppression rules in `visualization-system.md`) are inherited
from the project's visualization framework, not reinvented inside this
phase.

The reason core-flows has no review-pair phase is that the artifact is
verifiable on inspection. The user can read the rendered diagrams directly
and accept them or redirect; the load-bearing decisions in flows are about
what the system does, not about how it is structured, and the human can
judge that without a separate adversarial pass. The `tech-plan` band needs a
review pair because architectural decisions span boundaries, handle
failures, and define schemas in ways that benefit from explicit
stress-testing; the `core-flows` band does not.

The second addition is the `tech-plan` band: `tech-plan-spec` followed by
`tech-plan-review`. The `tech-plan-spec` phase produces `tech-plan.md` with
three sections -- Architectural Approach, Data Model, and Component
Architecture -- each rendered with appropriate visualizations per
`visualization-system.md`. Architectural Approach uses a `flowchart`
container view (CON) showing runtime processes, services, and data stores;
Component Architecture uses one or more `classDiagram` or `flowchart`
component views (CMP) per container; cross-component flows use
`sequenceDiagram` (SEQ); per-entity lifecycles use `stateDiagram-v2` (STT)
when warranted. The Data Model is expressed as fenced code blocks, not as
ER diagrams.

The third addition is the structural counterpart in `tech-plan-review`:
rewrite-or-loop-back review semantics, mirroring `plan-review` and
`milestone-review`. Internal findings are corrected in place via
`koan_artifact_write`; new-files findings yield with `tech-plan-spec`
recommended for loop-back. The user's phase-switch decision after the review
yield is the implicit acceptance moment; not pushing back IS acceptance. The
artifact's `status` taxonomy from `artifacts.md` is set conventionally
(`In-Progress` while the reviewer may rewrite; `Final` once the reviewer is
satisfied), but `Approved` is not enforced by any code path -- it is reserved
for a future structural-gating mechanism not introduced in this work.

## Artifacts produced by the initiative workflow

The artifact lifecycle from `artifacts.md` applies. The initiative workflow
produces the following artifacts.

| Artifact              | Lifetime         | Producer phase                                    | Reviewer phase     | Acceptance gate                                                                                                                                                                                 |
| --------------------- | ---------------- | ------------------------------------------------- | ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `brief.md`            | frozen           | `intake`                                          | (none)             | `Final` at intake exit                                                                                                                                                                          |
| `core-flows.md`       | frozen           | `core-flows`                                      | (none)             | `Final` at core-flows exit                                                                                                                                                                      |
| `tech-plan.md`        | disposable       | `tech-plan-spec`                                  | `tech-plan-review` | `Final` at tech-plan-review exit (no separate Approved gate; the user's phase-switch decision after the review yield is the implicit review moment, mirroring plan-review and milestone-review) |
| `milestones.md`       | additive-forward | `milestone-spec` (CREATE), `exec-review` (UPDATE) | `milestone-review` | (existing pattern)                                                                                                                                                                              |
| `plan-milestone-N.md` | disposable       | `plan-spec`                                       | `plan-review`      | (existing pattern)                                                                                                                                                                              |

`brief.md` retains its current `Final` exit semantics from intake.
`milestones.md` and `plan-milestone-N.md` retain the gating pattern used by
the existing milestones workflow; whether to upgrade those gates to use an
explicit acceptance surface is a separate design question the initiative work
deliberately does not settle.

## Cross-band trust

The trust model from `phase-trust.md` extends naturally. Each producer phase
trusts every upstream artifact in its accepted state. Each reviewer phase
applies rewrite-or-loop-back semantics: internal findings (the producer
should have caught these from material already in scope) are corrected
directly in the producer's artifact via `koan_artifact_write`; new-files
findings (catching these would have required loading material the producer
did not have access to) are surfaced via `koan_yield` with the producer
phase recommended for loop-back. For `tech-plan.md`, the reviewer surfaces
internal corrections via `koan_artifact_write` and yields; the user advances
to `milestone-spec` when the architecture is acceptable, or back to
`tech-plan-spec` for re-drafting.

## Compound-risk framing

The initiative workflow has more design surface than any other preset, and
errors at the upper bands compound through every subsequent band. A wrong
decision in tech-plan corrupts every milestone decomposition derived from
it; a wrong decomposition corrupts every plan; a wrong plan corrupts every
execution. This is the same compound-risk property that justifies the
adversarial review phases in the existing milestones workflow, scaled up to
the architectural band. The mitigation is the rewrite-or-loop-back pattern
in `tech-plan-review`: the reviewer corrects internal findings in place and
yields to the user for direction; the user's decision to advance to
`milestone-spec` (rather than back to `tech-plan-spec`) is the boundary
that bounds the architectural wrongness.

## When not to use initiative

The initiative workflow is not the right preset when the work is a focused
change touching a bounded area (use `plan`); when the work is multi-milestone
but the architecture is already implicit in the codebase (use `milestones`);
or when the user is not yet sure what they want (start in `discovery`,
which is the single-phase frame workflow, and promote to a delivery
workflow once the question is clear).

The cost of choosing initiative when one of the leaner presets would have
done is real, and the symptom is a `core-flows.md` or `tech-plan.md` whose
contents restate what was already obvious from the brief. If during
core-flows the agent finds itself transcribing intake findings rather than
describing genuinely new operational behavior, that is the signal to yield
and downgrade the workflow to `milestones`. If during tech-plan-spec the
architectural decisions reduce to "follow the existing pattern in the
codebase," the same signal applies.
