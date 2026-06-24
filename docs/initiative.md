# Initiative Workflow

The initiative workflow is the most complete preset koan offers. It runs the
full sequence of design-and-delivery phases for substantial undertakings whose
ceremony the leaner `plan` and `milestones` workflows cannot carry. The
workflow is structurally a superset of `milestones`: it adds two design-heavy
phases above milestone decomposition (`core-flows` and `tech-plan`),
reuses `milestone`, `plan`, `execute`, and `curation` unchanged from the
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

The full sequence is `intake -> core-flows -> tech-plan -> milestone ->
plan -> execute`, with the `plan -> execute` loop repeating once per
milestone, and `curation` as the terminal phase after the last milestone
is `[done]`.

The phases above `milestone` are what distinguish initiative from
milestones. Below `milestone`, the workflow is identical to the existing
milestones workflow and reuses the same phase modules with the same
guidance.

The `core-flows` phase is included in the standard initiative path but is
yield-skippable. When the operational behavior of the system is already
settled in the dialogue between the user and the agent during intake, the
user can yield from intake directly to `tech-plan` and the workflow
proceeds without writing `core-flows.md`. The `tech-plan` phase is not
skippable. If architectural reasoning is not warranted, the right preset
is `milestones`, not initiative without tech-plan.

The `frame` phase is not part of the initiative path. It is reachable from
any yield boundary in any workflow as an escape hatch when the user
discovers mid-workflow that they need to step back and explore. Frame lives
in the standalone `discovery` workflow and is described in
`workflow-phases.md`.

## What initiative adds beyond milestones

The first addition is `core-flows`, a phase whose responsibility is to
produce `core-flows.md`. The artifact is visualization-first by
construction: its load-bearing content is mermaid sequence diagrams over
the relevant actors, plus step narratives that describe triggers, sequenced
steps, and exit conditions. The artifact is constrained to the operational
level -- no file paths, no component names, no implementation detail. The
diagram contracts (one `sequenceDiagram` per flow, sized per the suppression
rules in `visualization-system.md`) are inherited from the project's
visualization framework, not reinvented inside this phase.

The reason core-flows has no mechanical reviewer is that the artifact is
verifiable on inspection. The user can read the rendered diagrams directly
and accept them or redirect; the load-bearing decisions in flows are about
what the system does, not about how it is structured, and the human can
judge that without an adversarial pass.

The second addition is the `tech-plan` phase. It produces `tech-plan.md`
with three sections -- Architectural Approach, Data Model, and Component
Architecture -- each rendered with appropriate visualizations per
`visualization-system.md`. Architectural Approach uses a `flowchart`
container view (CON) showing runtime processes, services, and data stores;
Component Architecture uses one or more `classDiagram` or `flowchart`
component views (CMP) per container; cross-component flows use
`sequenceDiagram` (SEQ); per-entity lifecycles use `stateDiagram-v2` (STT)
when warranted. The Data Model is expressed as fenced code blocks, not as
ER diagrams.

Writing `tech-plan.md` via `koan_artifact_write` triggers the mechanical
TECH_PLAN_REVIEWER as a blocking side-effect. The reviewer runs in a fresh
context, stress-tests the architectural decisions against simplicity,
flexibility, robustness, scaling, codebase fit, and consistency with upstream
artifacts, and returns findings to the producer. The producer reconciles
inline: incorporating valid findings via `koan_artifact_edit`, overruling
misconceptions, or escalating approach-invalidating findings via
`koan_ask_question`. After reconciliation the phase yields with `milestone`
suggested. The user's decision to advance to `milestone` is the implicit
acceptance moment.

## Artifacts produced by the initiative workflow

The artifact lifecycle from `artifacts.md` applies. The initiative workflow
produces the following artifacts.

| Artifact              | Producer phase | Mechanical reviewer  | Acceptance                                |
| --------------------- | -------------- | -------------------- | ----------------------------------------- |
| `brief.md`            | `intake`       | (none)               | Write-once at intake exit                 |
| `core-flows.md`       | `core-flows`   | (none)               | Write-once at core-flows exit             |
| `tech-plan.md`        | `tech-plan`    | `TECH_PLAN_REVIEWER` | Producer reconciles inline; user advances |
| `milestones.md`       | `milestone`    | `MILESTONE_REVIEWER` | Producer reconciles inline; user advances |
| `plan-milestone-N.md` | `plan`         | `PLAN_REVIEWER`      | Producer reconciles inline; user advances |

## Cross-band trust

The trust model from `phase-trust.md` extends naturally. Each producer phase
trusts every upstream artifact in its accepted state. The mechanical reviewer
pattern applies inline reconcile semantics: when `koan_artifact_write` is
called, the reviewer sub-agent runs in a fresh context, returns findings, and
the producer reconciles them in the same turn. Valid findings are incorporated
via `koan_artifact_edit`; misconceptions are overruled; approach-invalidating
findings are escalated via `koan_ask_question`. The producer then advances.

## Compound-risk framing

The initiative workflow has more design surface than any other preset, and
errors at the upper bands compound through every subsequent band. A wrong
decision in tech-plan corrupts every milestone decomposition derived from
it; a wrong decomposition corrupts every plan; a wrong plan corrupts every
execution. The mitigation is the TECH_PLAN_REVIEWER: the reviewer stress-
tests architectural decisions and returns findings to the producer before the
phase advances to `milestone`. The producer's reconciliation step (and the
user's implicit acceptance when they advance) is the boundary that bounds
architectural wrongness.

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
and downgrade the workflow to `milestones`. If during `tech-plan` the
architectural decisions reduce to "follow the existing pattern in the
codebase," the same signal applies.
