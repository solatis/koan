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
because its purpose is open-ended exploration that refuses nothing: the
user may bring feature design questions, bug hunting and troubleshooting
sessions, or general-purpose questions. It produces no fixed artifact;
its exit is negotiated with the user when they signal sufficient clarity.

The why band answers the question of intent. It captures what the user is
trying to accomplish, who is affected by the current state, and what makes
the initiative worth doing at all. Its artifact (`brief.md`) is write-once: created at intake exit and never
rewritten downstream, because revisiting intent during execution destabilizes
everything downstream.

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

The first is the mechanical reviewer pattern. For artifact families that
warrant adversarial check (milestones, plan, tech-plan), `koan_artifact_write`
triggers a REVIEWER sub-agent mechanically as a blocking side-effect of the
write call. The reviewer runs in a fresh context against the just-written
artifact and returns freeform findings directly to the producer as the tool
result. The producer reads them in the same turn and reconciles inline:
valid findings are incorporated via `koan_artifact_edit`; reviewer
misconceptions are overruled by editing in the missing context; approach-
invalidating findings are escalated via `koan_ask_question`. The producer
records each finding and its disposition inline in the artifact's `## Review`
section. There are no separate `*-review` phases and no `.review.md` sidecar;
review is a synchronous side-effect of the artifact write, not a separate
orchestrator turn.

Note that not every artifact family has a paired reviewer: `brief.md` and
`core-flows.md` have no mechanical reviewer. `brief.md` is frozen at intake
exit; `core-flows.md` is verifiable on inspection by the user against the
rendered diagrams.

The second pattern is trust forward. Downstream phases trust upstream
artifacts in their accepted state without re-evaluating them. If execution
reveals an upstream artifact to be wrong, the orchestrator can loop back to
the relevant phase and edit the living document in place -- but it does not
unilaterally rewrite or override upstream content unilaterally. The trust
model is documented in `phase-trust.md`.

The artifact model from `artifacts.md` continues to apply. Artifacts are
living working surfaces; `brief.md` is the sole write-once artifact.

## Phase taxonomy

The phases below are listed in band order. Each phase is described by its
responsibility, its position relative to neighbors, the artifacts it reads
and writes, the dominant kinds of tool calls it makes, the termination
condition that closes the phase, and the contract boundary it must not
cross.

### frame (discovery band)

The frame phase is the only divergent phase in the system. Its
responsibility is to support open-ended exploration for whatever the user
brings: feature design questions, bug hunting and troubleshooting sessions,
or general-purpose questions. The agent refuses nothing. It may analyze,
investigate, troubleshoot, draw conclusions, and make recommendations,
subject only to a light guardrail: if the agent is about to recommend a
large, hard-to-reverse architectural direction, it names it as a decision
and lets the user choose rather than committing silently.

This phase has no required upstream phase. It is the entry point for the
standalone `discovery` workflow, and it is also reachable from any yield
boundary in any other workflow as an escape hatch when the user discovers
mid-workflow that they need to step back. Its downstream behavior is
determined at exit and is one of three options: promotion into another
workflow with the exploration transcript carried forward as initial
context, transition to another phase within the current workflow, or exit
with no artifact and no further phase.

The frame phase produces no fixed artifact. At exit, the agent asks the
user what artifact shape, if any, is appropriate. Whatever is chosen is
written then, not before.

The dominant tool-call shape is terminal-text turns for open-ended conversation
(the loop parks after each hand-back and resumes on the user's reply),
supplemented by `koan_search`, `koan_reflect`, and `koan_ask_question` to
surface prior context and clarify intent. `koan_request_scouts`, `bash`,
and direct file reading (Read / Grep / Glob) are available and used for
bug hunting and troubleshooting when the question calls for codebase
investigation. No artifact-writing tools are called until the user signals
exit.

The termination condition is user-driven and explicit. The phase does not
auto-advance under any circumstance; it always yields back to the user.
The contract boundary is that frame must flag large architectural
commitments rather than decide them silently, must not write any decision
into project memory unless the user explicitly directs curation, and must
not produce a brief.md or any other workflow artifact without negotiating
its shape with the user first.

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
workflow the next phase is `core-flows` (or `tech-plan` when
core-flows is yield-skipped); in milestones it is `milestone`; in
plan it is `plan`.

The dominant tool-call shape is `koan_ask_question` for structured user
dialogue, `koan_request_scouts` for codebase exploration of unfamiliar
subsystems, `koan_search` and `koan_reflect` to consult prior project
memory, and `koan_artifact_write` for the terminal `brief.md` write. The
termination condition is the writing of `brief.md`, at which point the
phase auto-advances to the configured next phase.

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
chooses whether to proceed to `tech-plan`, loop back to `core-flows`
for revision, or pivot elsewhere.

Upstream of core-flows is intake. Downstream is `tech-plan` when the
user confirms, or `core-flows` (loop-back) when the user redirects. The
phase yields rather than auto-advancing because user direction is
required to choose the downstream phase.

The dominant tool-call shape is `koan_ask_question` for clarifying
interactions and exit conditions, `koan_artifact_read` for upstream
artifacts, and `koan_artifact_write` for the terminal `core-flows.md`
write. Scout dispatch is rarely warranted because the work is about
externally visible behavior rather than codebase structure; the
registered toolset (`compose_toolset`) allows it but a wrong-phase call returns
a recoverable error from `phase_gate_message`; prompt discipline should also
discourage it.

The termination condition is the writing of `core-flows.md` followed by
yield. The contract boundary is that core-flows must not include
component diagrams, file references, or implementation detail.
Architectural reasoning is the next phase's job.

The phase is included in the standard initiative path but is yield-skippable.
When the operational behavior is settled in dialogue and writing it down
adds nothing, the user can yield from intake directly to `tech-plan`.

### tech-plan (what-system band)

The tech-plan phase produces the system architecture artifact. It is
the structural counterpart to core-flows: where core-flows describes
externally visible behavior, tech-plan describes internal structure.
The artifact contains three load-bearing sections -- Architectural
Approach, Data Model, and Component Architecture -- each rendered with
appropriate visualization per the slot mapping in
`visualization-system.md`. Architectural Approach uses CON (a `flowchart`
container view); Component Architecture uses CMP (`classDiagram` or
`flowchart` per component); cross-component flows use SEQ
(`sequenceDiagram`); per-entity lifecycles use STT (`stateDiagram-v2`)
when warranted. Data Model is expressed as fenced code blocks for
schema definitions, not as ER diagrams.

The visualization requirement is not stylistic. It is the mechanism by
which the architecture becomes inspectable rather than buried in prose,
and it is what gives the TECH_PLAN_REVIEWER (triggered on
`koan_artifact_write`) material to stress-test.

The phase reads `brief.md`, `core-flows.md` when present, and the
codebase. It writes `tech-plan.md` as a disposable artifact that
downstream phases consume but do not modify. Each section captures the
chosen path and the rejected alternatives with rationale.

Upstream is either core-flows (in initiative runs that include the
flows phase) or intake directly (when core-flows is yield-skipped).
Downstream is `milestone`.

The dominant tool-call shape is `koan_request_scouts` for codebase
exploration when the architecture must integrate with existing
structure, `koan_ask_question` for binary architectural questions when
genuine alternatives exist, `koan_search` and `koan_reflect` to consult
prior architectural decisions in memory, and `koan_artifact_write` for
the terminal write of `tech-plan.md` (which triggers the mechanical
TECH_PLAN_REVIEWER and returns its findings to the producer).

The termination condition is the write of `tech-plan.md`, followed by
inline reconciliation of the TECH_PLAN_REVIEWER's findings, at which
point the phase yields with `milestone` suggested. The contract boundary
is that tech-plan must not specify implementation steps for individual
files or functions; that is the HOW band's job.

### milestone, plan, execute (how band)

These phases compose the delivery loop of the milestones and initiative
workflows. Their responsibilities, contracts, and tool-call shapes are
documented in `milestones.md` (for `milestone` in particular) and
`phase-trust.md` (for the trust and reconcile model). The initiative
preset binds them with the same modules, the same per-phase guidance
text, and the same suggested-phase behavior used in the milestones
workflow.

The one difference visible to these phases when running inside an
initiative workflow is that `tech-plan.md` is present in the artifact
set, and the per-phase guidance for `milestone` and `plan` references it
as an authoritative source for the architectural decisions that
constrain decomposition and per-milestone plans. The artifact is read
via `koan_artifact_read`; no new tool is needed.

The `milestone` phase is one-time. The orchestrator decomposes the initiative
into milestones on first entry and edits `milestones.md` in place thereafter;
there is no re-entry or discard hook.

The `plan` phase produces `plan-milestone-N.md` (milestones workflow) or
`plan.md` (plan workflow). Writing the artifact triggers the mechanical
PLAN_REVIEWER; the producer reconciles findings inline before advancing.

The `execute` phase is entered via `koan_set_phase("execute")` (pure routing).
Inside the phase the orchestrator calls `koan_request_executor(plan_file?,
instructions?)` to spawn the executor, which returns a deviation report. The
orchestrator verifies independently, then classifies the outcome: conforming
results are recorded inline in the plan (`## Execution N`) and the orchestrator
advances; non-conforming results lead to in-place plan edits or free-form fix
instructions and a re-run. Re-execution is the orchestrator's agency -- it may
call `koan_request_executor` any number of times before escalating.

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

The plan workflow runs `intake -> plan -> execute -> curation`. Its use
case is a focused change touching a bounded area where multi-milestone
decomposition and architectural reasoning are not needed. Review of the
plan is performed inline by the mechanical PLAN_REVIEWER on
`koan_artifact_write`; there is no separate `plan-review` phase. Execution
is launched explicitly via `koan_request_executor` from within the execute
phase.

The milestones workflow runs `intake -> milestone -> plan -> execute`
with the plan-through-execute sub-loop repeating once per milestone, and
`curation` as the terminal phase. Its use case is a multi-milestone
initiative where the architecture is implicit in the existing codebase.
Review of milestones and plans is mechanical and inline.

The initiative workflow runs `intake -> core-flows -> tech-plan ->
milestone -> plan -> execute` with the same sub-loop and curation
termination. The `core-flows` phase is yield-skippable. Its use case is
a multi-milestone initiative where architectural decisions cross multiple
milestones and warrant a load-bearing artifact, and where the operational
behavior is itself worth describing as a shared artifact. Review of
tech-plan, milestones, and plans is mechanical and inline. See
`initiative.md` for the full contract.

The discovery workflow is a single-phase preset: `frame -> exit`. The
preset has no other phases. Its use case is open-ended exploration --
the user may bring feature design questions, bug hunting and
troubleshooting sessions, or any general question. The agent refuses
nothing and may investigate the codebase directly when the question
calls for it. The exit is negotiated; the user may choose to write a
brief or a tech-plan sketch at exit, write nothing, or transition into
a delivery workflow with the exploration transcript carried forward as
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
workflow via `koan_set_workflow`. When a tech-plan run reveals
that the user does not actually know what they want, the user can
yield, switch into discovery, explore, and either return to
tech-plan with new direction (via another `koan_set_workflow`
call) or pivot the workflow shape entirely.

Architectural lookback allows the workflow to invoke tech-plan
from a later band when execution surfaces an architectural question
that was elided. If a milestone's execute phase deviation report
reveals an architectural assumption that turns out to be wrong, the
user can yield from execute into tech-plan rather than back into
milestone. The graph permits this because the underlying transition
rule is any-to-any except self-transition; the workflow's `transitions`
dict only encodes the suggested defaults, not constraints.

## Toolset composition implications

New phases need entries in the toolset allowlist tables at
`koan/tools/tool_policy.py`. The `_ORCHESTRATOR_SCOUT_PHASES` frozenset
lists `intake`, `core-flows`, `tech-plan`, `milestone`, `plan`,
`curation`, and `frame`. `_ORCHESTRATOR_BASH_PHASES` lists `execute` and
`frame`. The `frame` phase is included in both frozensets to support bug
hunting and troubleshooting, which require codebase investigation via
scouts, bash, and direct file reading. `compose_toolset` consults these
frozensets when building the tool vocabulary for a given (role, phase) pair.

## Producer-and-reviewer summary

Review is mechanical and inline: `koan_artifact_write` triggers the
reviewer sub-agent as a blocking side-effect for the reviewed artifact
families below. No separate `*-review` phases exist.

| Producer     | Artifact                          | Mechanical reviewer  | Reconcile by                                  |
| ------------ | --------------------------------- | -------------------- | --------------------------------------------- |
| `intake`     | `brief.md`                        | (none)               | Write-once at intake exit                     |
| `core-flows` | `core-flows.md`                   | (none)               | Write-once at core-flows exit                 |
| `tech-plan`  | `tech-plan.md`                    | `TECH_PLAN_REVIEWER` | Producer edits inline; records in `## Review` |
| `milestone`  | `milestones.md`                   | `MILESTONE_REVIEWER` | Producer edits inline; records in `## Review` |
| `plan`       | `plan.md` / `plan-milestone-N.md` | `PLAN_REVIEWER`      | Producer edits inline; records in `## Review` |
