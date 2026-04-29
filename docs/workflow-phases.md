# Workflow Phases

This document is the authoritative reference for koan's phase taxonomy. It
catalogs every phase the system supports across all workflows, describes the
responsibilities each phase carries, names the artifacts each phase reads
and writes, and characterizes how phases relate to their upstream and
downstream neighbors. Step-level mechanics — what individual sub-steps a
phase runs internally — are out of scope here; those live in the per-phase
modules under `koan/phases/` and in the targeted spoke documents
(`intake-loop.md`, `milestones.md`, `phase-trust.md`).

> Parent doc: [architecture.md](./architecture.md)
> Workflow presets: [initiative.md](./initiative.md)
> Trust model: [phase-trust.md](./phase-trust.md)
> Artifact lifecycle: [artifacts.md](./artifacts.md)
> Diagram contracts: [visualization-system.md](./visualization-system.md)

## The architectural model

Koan's phases group into five conceptual bands by what question they
answer. The bands are sequenced in the most general path, but no preset
uses all of them, and the user can deviate at any boundary because koan's
transitions allow any-to-any movement within a workflow's available
phases.

The discovery band is divergent. It exists outside the linear path
because its purpose is open-ended exploration before a question is
well-formed. It produces no fixed artifact; its exit is negotiated with
the user when they signal sufficient clarity.

The why band answers the question of intent. It captures what the user is
trying to accomplish, who is affected by the current state, and what makes
the initiative worth doing at all. Its artifact is intended to remain
frozen for the rest of the run because revisiting intent during execution
destabilizes everything downstream.

The what band answers the question of definition. It splits into two
sub-bands. The first describes the system's externally visible behavior —
flows over actors, triggers, and outcomes — without reference to file
paths or component names. The second describes the system's internal
structure: the architectural approach, the data model, and the component
boundaries. Both sub-bands are visualization-first by construction
following the contracts in `visualization-system.md`, and both are
designed to be human-readable and human-validatable before any HOW
commitments are made.

The how band answers the question of execution. It contains decomposition
(how the work splits into ordered units), per-unit implementation (how
each unit is to be built), the executor handoff itself, and the
verification that the executor actually produced what the plan described.
This is the only band that modifies code.

The closing band captures lessons from the run into project memory and
exits.

## Two patterns governing phase relationships

Two patterns govern how phases relate within and across these bands.

The first is producer-validator pairing. Some bands have both a phase that
writes the artifact and a phase that subjects it to adversarial check
before the next band starts. Today the pattern exists for milestone-spec
and milestone-review, plan-spec and plan-review, and execute and
exec-review. The initiative workflow extends this pattern to tech-plan-spec
and tech-plan-review at the architectural layer. Note that not every
band has a paired reviewer: intake's `brief.md` is `Final` at exit without
a separate review phase, and `core-flows.md` similarly does not have a
paired reviewer because the artifact is verifiable on inspection by the
user against the rendered diagrams.

The second pattern is trust forward, falsify backward. Downstream phases
trust upstream artifacts in their accepted state without re-evaluating
them. A downstream phase can request a loop-back when reality reveals an
upstream artifact to be wrong, but it does not unilaterally rewrite or
override upstream content. The trust model is documented in
`phase-trust.md`.

The artifact lifecycle from `artifacts.md` continues to apply. Artifacts
are classified as frozen, additive-forward, or disposable. The status
taxonomy of `Draft -> In-Progress -> Approved -> Final` exists in
`koan/artifacts.py:STATUS_VALUES`, but the `Approved` value is not
currently enforced by any code path -- it is reserved for a future
structural-gating mechanism. The gate at `tech-plan-review` is
conventional: the reviewer applies rewrite-or-loop-back semantics and
yields; the user's phase-switch decision (advance to `milestone-spec` or
loop back to `tech-plan-spec`) is the implicit acceptance moment.

## Phase taxonomy

The phases below are listed in band order. Each phase is described by its
responsibility, its position relative to neighbors, the artifacts it reads
and writes, the dominant kinds of tool calls it makes, the termination
condition that closes the phase, and the contract boundary it must not
cross.

### frame (discovery band)

The frame phase is the only divergent phase in the system. Its
responsibility is to support open-ended dialogue with the user when the
user is not yet sure what they want, what shape it should take, or whether
they want to build it at all. The agent's role is closer to a sounding
board than an analyst: it surfaces tradeoffs, names hidden assumptions,
offers alternatives, and pushes back on premature commitment, without
converging on an artifact unless the user signals readiness.

This phase has no required upstream phase. It is the entry point for the
standalone `discovery` workflow, and it is also reachable from any yield
boundary in any other workflow as an escape hatch when the user discovers
mid-workflow that they need to step back. Its downstream behavior is
determined at exit and is one of three options: promotion into another
workflow with the discovery transcript carried forward as initial
context, transition to another phase within the current workflow, or exit
with no artifact and no further phase.

The frame phase produces no fixed artifact. At exit, the agent asks the
user what artifact shape, if any, is appropriate. Whatever is chosen is
written then, not before.

The dominant tool-call shape is `koan_yield` for open-ended conversation,
supplemented by `koan_search` and `koan_reflect` to surface relevant
prior context from project memory. `koan_request_scouts` is technically
available but is discouraged via prompt discipline because the phase is
exploratory rather than investigative; codebase reading is appropriate
when the dialogue starts referring to specific systems, not as a
default. No artifact-writing tools are called until the user signals
exit.

The termination condition is user-driven and explicit. The phase does
not auto-advance under any circumstance; it always yields back to the
user. The contract boundary is that frame must not commit to
architectural choices, must not write any decision into project memory
unless the user explicitly directs curation, and must not produce a
brief.md or any other workflow artifact without negotiating its shape
with the user first.

### intake (why band)

The intake phase establishes shared understanding of the user's intent
and grounds it against the current state of the codebase. The phase is
the most consequential phase in any workflow that uses it, because every
downstream phase reads its output as authoritative.

The phase reads the user's task description, the conversation that
preceded the workflow, and selectively reads codebase files to verify
references made in the dialogue. It produces `brief.md`, the frozen
authoritative initiative artifact for the rest of the run.

Upstream of intake is either the user's initial request or a frame-phase
exit. Downstream depends on the workflow preset: in the initiative
workflow the next phase is `core-flows` (or `tech-plan-spec` when
core-flows is yield-skipped); in milestones it is `milestone-spec`; in
plan it is `plan-spec`.

The dominant tool-call shape is `koan_ask_question` for structured user
dialogue, `koan_request_scouts` for codebase exploration of unfamiliar
subsystems, `koan_search` and `koan_reflect` to consult prior project
memory, and `koan_artifact_write` for the terminal `brief.md` write. The
termination condition is the writing of `brief.md` with `Final` status,
at which point the phase auto-advances to the configured next phase.

The contract boundary is that intake must not infer architectural
decisions, propose implementation approaches, or define work units.
Intake captures what was said and what was verified; the WHAT and HOW
bands are responsible for inventing structure. The current `intake.py`
system prompt enforces this correctly.

### core-flows (what-experience band)

The core-flows phase produces a visualization-first description of the
system's externally visible behavior. It is the koan equivalent of
Traycer's core-flows, generalized so the persona is not necessarily a
human user. The persona can be an executor agent, the orchestrator, an
external system, or another subsystem; what matters is that the artifact
captures operational behavior at the actor-and-trigger level rather than
at the component-and-file level.

The artifact's discipline is that flows are described with concrete
actors, triggers, sequenced steps, and exit conditions, but without file
paths, component names, or implementation detail. This constraint is
what makes the artifact a surface the human can validate without having
to read like an engineer. The artifact's load-bearing content is
mermaid `sequenceDiagram` blocks per flow (one SEQ per flow per the
contracts in `visualization-system.md`), each accompanied by step
narrative.

This phase has no paired review phase. The artifact is verifiable on
inspection by the user against the rendered diagrams, and the load-bearing
decisions are about what the system does rather than how it is
structured. The user yields with the core-flows artifact in hand and
chooses whether to proceed to `tech-plan-spec`, loop back to `core-flows`
for revision, or pivot elsewhere.

Upstream of core-flows is intake. Downstream is `tech-plan-spec` when the
user confirms, or `core-flows` (loop-back) when the user redirects. The
phase yields rather than auto-advancing because user direction is
required to choose the downstream phase.

The dominant tool-call shape is `koan_ask_question` for clarifying
interactions and exit conditions, `koan_artifact_view` for upstream
artifacts, and `koan_artifact_write` for the terminal `core-flows.md`
write. Scout dispatch is rarely warranted because the work is about
externally visible behavior rather than codebase structure; the
permission fence allows it but prompt discipline should discourage it.

The termination condition is the writing of `core-flows.md` followed by
yield. The contract boundary is that core-flows must not include
component diagrams, file references, or implementation detail.
Architectural reasoning is the next phase's job.

The phase is included in the standard initiative path but is yield-skippable.
When the operational behavior is settled in dialogue and writing it down
adds nothing, the user can yield from intake directly to `tech-plan-spec`.

### tech-plan-spec (what-system band, producer)

The tech-plan-spec phase produces the system architecture artifact. It is
the structural counterpart to core-flows: where core-flows describes
externally visible behavior, tech-plan-spec describes internal structure.
The artifact contains three load-bearing sections — Architectural
Approach, Data Model, and Component Architecture — each rendered with
appropriate visualization per the slot mapping in
`visualization-system.md`. Architectural Approach uses CON (a `flowchart`
container view); Component Architecture uses CMP (`classDiagram` or
`flowchart` per component); cross-component flows use SEQ
(`sequenceDiagram`); per-entity lifecycles use STT (`stateDiagram-v2`)
when warranted. Data Model is expressed as fenced code blocks for
schema definitions, not as ER diagrams.

The visualization requirement is not stylistic. It is the mechanism by
which the architecture becomes inspectable rather than buried in prose,
and it is the foundation that makes the human-acceptance gate at
tech-plan-review meaningful.

The phase reads `brief.md`, `core-flows.md` when present, and the
codebase. It writes `tech-plan.md` as a disposable artifact that
downstream phases consume but do not modify. Each section captures the
chosen path and the rejected alternatives with rationale, so the
reviewer phase has something to stress-test.

Upstream is either core-flows (in initiative runs that include the
flows phase) or intake directly (when core-flows is yield-skipped).
Downstream is tech-plan-review.

The dominant tool-call shape is `koan_request_scouts` for codebase
exploration when the architecture must integrate with existing
structure, `koan_ask_question` for binary architectural questions when
genuine alternatives exist, `koan_search` and `koan_reflect` to consult
prior architectural decisions in memory, and `koan_artifact_write` for
the terminal write of `tech-plan.md`.

The termination condition is the writing of `tech-plan.md`, after which
the phase auto-advances to `tech-plan-review`. The contract boundary is
that tech-plan-spec must not specify implementation steps for individual
files or functions; that is the HOW band's job.

### tech-plan-review (what-system band, validator)

The tech-plan-review phase is the adversarial reviewer for the
architecture artifact. It mirrors Traycer's architecture-validation
discipline: the reviewer extracts the three to seven critical
architectural decisions that cross boundaries, handle failures, define
schemas, or break from existing patterns, then stress-tests each against
simplicity, flexibility, robustness, scaling, codebase fit, and
consistency with the upstream artifacts. The review additionally checks
the diagrams themselves for accuracy: do the nodes correspond to
actually-introduced components, do the edges describe real protocols, do
the suppression decisions match the threshold rules in
`visualization-system.md`, does the level separation hold per slot.

Internal findings are corrected directly in `tech-plan.md` via
`koan_artifact_write` per the rewrite-or-loop-back rule; new-files
findings are surfaced via `koan_yield` with `tech-plan-spec` recommended
for loop-back. The phase yields after evaluation; the user's phase-switch
decision (forward to `milestone-spec` or back to `tech-plan-spec`) is the
implicit acceptance moment, mirroring plan-review and milestone-review.
The `Approved` value in the artifact status taxonomy is not enforced in
this workflow.

Upstream is tech-plan-spec; downstream is `milestone-spec` when the
architecture is acceptable, or `tech-plan-spec` on loop-back. The phase
does not auto-advance.

The dominant tool-call shape is `koan_artifact_view` to read
`tech-plan.md`, `core-flows.md`, and `brief.md`; `koan_request_scouts` to
verify architectural claims about integration points (scouts are sanctioned
and encouraged in this phase -- unlike plan-review, mechanical accuracy is
not the concern; integration-point claims must be verified now, before
milestone decomposition assumes them); `koan_artifact_write` for internal-
finding corrections; and `koan_yield` to surface the review outcome and
next-phase suggestions.

The contract boundary is that tech-plan-review must not introduce
architectural decisions of its own. It stress-tests and confirms but
does not author. If a stress-test reveals a missing decision, the
correct response is to recommend a loop-back to tech-plan-spec, not
to write the decision in.

### milestone-spec, milestone-review, plan-spec, plan-review, execute, exec-review (how band)

These phases are reused unchanged from the existing milestones workflow
in the initiative preset. Their responsibilities, contracts, and
tool-call shapes are documented in `milestones.md` (for milestone-spec
in particular) and `phase-trust.md` (for the trust and verification
model). The initiative preset binds them into its workflow definition
with the same modules, the same per-phase guidance text, and the same
auto-advance behavior used in the milestones workflow.

The one difference visible to these phases when running inside an
initiative workflow is that `tech-plan.md` is present in the
artifact set, and the per-phase guidance for milestone-spec and
plan-spec should reference it as an authoritative source for the
architectural decisions that constrain decomposition and per-milestone
plans. The artifact is read via `koan_artifact_view`; no new tool is
needed.

### curation (closing band)

The curation phase is reused unchanged from the existing workflows. Its
responsibilities are documented in `koan/phases/curation.py` and the
postmortem and standalone directives in `koan/lib/workflows.py`.

## Workflow presets

A workflow preset is a default starting point and a default sequence of
auto-advance bindings through the phase graph. The user can deviate at
any yield boundary because `is_valid_transition` permits any-to-any
movement within a workflow's available phases except self-transition.
Presets exist to let common shapes start without configuration while
leaving the underlying graph open.

Koan ships with three delivery presets and two single-purpose presets:

The plan workflow runs `intake → plan-spec → plan-review → execute →
exec-review → curation`. Its use case is a focused change touching a
bounded area where adversarial review of the plan is worth the cost,
but multi-milestone decomposition and architectural reasoning are not.
This is the existing `plan` workflow.

The milestones workflow runs `intake → milestone-spec → milestone-review
→ plan-spec → plan-review → execute → exec-review` with the
plan-through-exec-review sub-loop repeating once per milestone, and
`curation` as the terminal phase. Its use case is a multi-milestone
initiative where the architecture is implicit in the existing codebase.
This is the existing `milestones` workflow.

The initiative workflow runs `intake → core-flows → tech-plan-spec →
tech-plan-review → milestone-spec → milestone-review → plan-spec →
plan-review → execute → exec-review` with the same sub-loop and
curation termination. The `core-flows` phase is yield-skippable. Its
use case is a multi-milestone initiative where architectural decisions
cross multiple milestones and warrant a load-bearing artifact, and
where the operational behavior is itself worth describing as a shared
artifact. See `initiative.md` for the full contract.

The discovery workflow is a single-phase preset: `frame → exit`. The
preset has no other phases. Its use case is open-ended thinking when
the user is not sure what they want and wants the agent as a sounding
board. The exit is negotiated; the user may choose to write a brief or
a tech-plan sketch at exit, write nothing, or transition into a
delivery workflow with the discovery transcript carried forward as
context. This workflow is structurally identical in shape to the
existing single-phase `curation` workflow, which serves as the
implementation precedent.

The curation workflow is a single-phase preset for standalone memory
maintenance. It is the existing `curation` workflow and is unchanged.

## Re-entry shapes

Two re-entry patterns are worth naming because they are not workflow
presets in their own right but graph operations that any preset
supports.

Discovery re-entry allows any workflow to drop into `frame` from any
yield boundary by transitioning into the standalone `discovery`
workflow via `koan_set_workflow`. When a tech-plan-spec run reveals
that the user does not actually know what they want, the user can
yield, switch into discovery, explore, and either return to
tech-plan-spec with new direction (via another `koan_set_workflow`
call) or pivot the workflow shape entirely.

Architectural lookback allows the workflow to invoke tech-plan-spec
or tech-plan-review from a later band when execution surfaces an
architectural question that was elided. If a milestone's exec-review
finds that a deviation traces back to an architectural assumption
that turns out to be wrong, the user can yield from exec-review into
tech-plan-spec rather than into milestone-spec. The graph permits
this because the underlying transition rule is any-to-any except
self-transition; the workflow's `transitions` dict only encodes the
suggested defaults, not constraints.

## Permission fence implications

The new phases need entries in the MCP permission fence at
`koan/lib/permissions.py`. The `_ORCHESTRATOR_SCOUT_PHASES` frozenset
lists `core-flows`, `tech-plan-spec`, and `tech-plan-review` (the legacy
bare `tech-plan` entry was replaced by the spec/review pair). The `frame`
phase is intentionally absent from the scout-phases set; scout access in
frame is denied at the fence layer because the phase's purpose is
exploration of intent rather than codebase investigation.

## Producer-and-acceptance summary

The initiative workflow uses the same rewrite-or-loop-back pattern for
`tech-plan-review` that the existing workflows use for `plan-review` and
`milestone-review`. No explicit `Approved` gate is enforced. Other
artifacts follow the patterns already in use: `brief.md` and
`core-flows.md` are `Final` at their respective phase exits; `milestones.md`
and `plan-milestone-N.md` follow the existing milestones-workflow gating
pattern.

| Producer         | Artifact              | Reviewer           | Initiative gate                                          |
| ---------------- | --------------------- | ------------------ | -------------------------------------------------------- |
| `intake`         | `brief.md`            | (none)             | `Final` at intake exit                                   |
| `core-flows`     | `core-flows.md`       | (none)             | `Final` at core-flows exit                               |
| `tech-plan-spec` | `tech-plan.md`        | `tech-plan-review` | `Final` at tech-plan-review exit; user advances manually |
| `milestone-spec` | `milestones.md`       | `milestone-review` | (existing milestones pattern)                            |
| `plan-spec`      | `plan-milestone-N.md` | `plan-review`      | (existing milestones pattern)                            |
| `execute`        | (no artifact)         | `exec-review`      | (verification-driven)                                    |
