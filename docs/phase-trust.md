# Phase Trust Model

Design decision document for how phases relate to each other's outputs and
how the mechanical reviewer pattern applies adversarial checking to producer
artifacts.

## Principle

The mechanical reviewer pattern applies **inline reconcile** semantics. For
each finding returned by the reviewer sub-agent, the producer classifies it
and acts immediately in the same turn:

- **INCORPORATED**: valid finding -- edit the artifact in place via
  `koan_artifact_edit`.
- **OVERRULED**: reviewer misconception -- edit in the missing context so
  downstream phases are not misled.
- **ESCALATED**: approach-invalidating finding -- surface via
  `koan_ask_question` and block until the user directs resolution.

The producer records each finding and its disposition inline in the same
artifact (a `## Review` section), so the review thread is preserved alongside
the content it concerns.

All other phases trust the chain. Re-verification outside the producer's
own reconcile step is the "intrinsic self-correction" anti-pattern and is
explicitly rejected in this project.

## Why the model changed

Before M6, review was performed by separate orchestrator phases
(`plan-review`, `milestone-review`, `tech-plan-review`, `exec-review`).
Each review phase ran as a distinct workflow step: the producer wrote the
artifact, yielded to the user, the user advanced to the review phase, and
the reviewer either rewrote the artifact in place or recommended a loop-back.

M6 collapses this into the mechanical reviewer sub-agent (M3). The reviewer
runs as a blocking side-effect of `koan_artifact_write`, returns findings
directly to the producer, and the producer reconciles in the same turn. This
eliminates the yield-and-advance ceremony for the common case (internal
findings correctable without new information) while preserving escalation
for the rare case where the producer needs the user's direction.

## The classification rule

For each finding, the producer judges: **can this be resolved from the
material already loaded in this turn?** The producer's loaded context is:

- The artifact body it just wrote (milestones.md, plan-milestone-N.md,
  tech-plan.md)
- `brief.md` (the frozen initiative scope, decisions, and constraints)
- Any codebase files loaded during the Analyze step

If yes -> **INCORPORATED** -> edit the artifact in place via `koan_artifact_edit`.

If no (resolving this would require new information the producer does not
have) -> **ESCALATED** -> `koan_ask_question` blocks until the user decides.

If the finding is factually wrong about the artifact or the codebase ->
**OVERRULED** -> edit the artifact to add the missing context, so the
inline `## Review` record reflects why the finding was dismissed.

## Per-phase responsibilities

### intake (3 steps: Gather, Deepen, Summarize)

- Explores the codebase, asks the user targeted questions, resolves ambiguity.
- Writes `brief.md` (frozen after intake).
- Downstream phases trust intake's findings as their starting point.
- No mechanical reviewer; `brief.md` is final at exit.

### milestone (2 steps: Analyze, Write) -- milestones workflow only

- One-time phase: decomposes the initiative into milestones grounded in code
  structure. The milestone phase is entered once; `milestones.md` is edited
  in place thereafter as understanding evolves.
- MUST NOT mark milestones `[done]` or add Outcome sections -- the execute
  phase's conformance review and inline bookkeeping own those transitions.
- Writing `milestones.md` triggers the MILESTONE_REVIEWER. Producer
  reconciles findings inline, recording them in the artifact's `## Review`
  section.

### plan (2 steps: Analyze, Write)

- Reads codebase files to write precise implementation instructions.
- In milestones workflow: scoped to the current `[in-progress]` milestone.
  Produces `plan-milestone-N.md`. Reads prior milestone Outcome sections for
  integration points, patterns, and constraints established by prior
  milestones.
- In plan workflow: produces `plan.md`.
- Writing the plan artifact triggers the PLAN_REVIEWER. Producer reconciles
  findings inline.

### execute (3 steps: Run, Verify, Reconcile)

- Entered via `koan_set_phase("execute")` from the plan phase.
- The orchestrator calls `koan_request_executor(plan_file?, instructions?)`
  to spawn the executor sub-agent, which returns a deviation report.
- The orchestrator runs independent verification (bash checks) -- the result
  is authoritative over the executor's self-report.
- The orchestrator classifies the outcome:
  - Conforming: record the outcome inline in the plan (`## Execution N
[CONFORMING]`); in the milestones workflow, mark the milestone `[done]`
    and append the four-subsection Outcome; then yield with the next-phase
    suggestion.
  - Non-conforming: edit the plan in place or compose free-form fix
    instructions, then call `koan_request_executor` again. Re-execution is
    the orchestrator's agency; there is no fixed remediation count.
  - Repeated non-conforming: escalate via `koan_ask_question`.

### tech-plan (2 steps: Analyze, Write) -- initiative workflow only

- Reads `brief.md`, `core-flows.md` (when present), and the codebase.
- Produces `tech-plan.md` with three sections: Architectural Approach,
  Data Model, Component Architecture.
- Writing `tech-plan.md` triggers the TECH_PLAN_REVIEWER. Producer
  reconciles findings inline, then yields with `milestone` suggested.

## Permission model

The permission model uses **role-level grant + prompt discipline**:

| Layer             | Mechanism                                              |
| ----------------- | ------------------------------------------------------ |
| Role-level grant  | `koan_artifact_edit` composed into the `orchestrator`  |
|                   | toolset unconditionally via `compose_toolset`          |
| Prompt discipline | Each phase is instructed to edit only its own artifact |
| Reviewer role     | `reviewer` role has no write tools; read-only          |

The reviewer sub-agent is restricted by construction: it receives only
`Read`, `Bash`, `Glob`, and `Grep` built-in tools and no koan write
tools. It cannot modify the artifact it reviews; it can only return
findings. The producer holds the write capability and makes all
editorial decisions.

## Data flow: plan workflow

```
brief.md (write-once, written by intake)
    |
    v
plan ----> plan.md
    |      koan_artifact_write triggers PLAN_REVIEWER (blocking)
    |      producer reconciles inline, edits plan.md,
    |      records review thread in plan.md ## Review section
    v
koan_set_phase("execute")
    |      pure routing -- no plan frozen, no executor spawned
    v
execute phase:
    |      koan_request_executor(plan_file="plan.md")
    |      executor runs, returns deviation report
    |      orchestrator verifies independently (bash checks)
    |      -- conforming: record ## Execution N inline; hand back (suggest curation)
    |      -- non-conforming: edit plan / compose instructions, re-run
    v
curation
```

## Data flow: milestones workflow

```
brief.md (write-once, written by intake)
    |
    v
milestone (one-time) ----> milestones.md
    |      koan_artifact_write triggers MILESTONE_REVIEWER (blocking)
    |      producer reconciles inline, edits milestones.md,
    |      records review thread in milestones.md ## Review section
    |      yields with "plan" suggested
    v
plan ----> plan-milestone-N.md   (reads prior Outcome sections)
    |      koan_artifact_write triggers PLAN_REVIEWER (blocking)
    |      producer reconciles inline; yields with "execute" suggested
    v
execute phase:
    |      koan_request_executor(plan_file="plan-milestone-N.md")
    |      executor runs, returns deviation report
    |      orchestrator verifies independently (bash checks)
    |      -- conforming: record ## Execution N inline; mark milestone [done],
    |         append four-subsection Outcome, advance next [pending] -> [in-progress]
    |      -- non-conforming: edit plan / compose instructions, re-run
    |
    +---> [if milestones remain] hand back (suggest plan) -> LOOP
    |
    +---> [if all done/skipped] hand back (suggest curation)
```

## Open questions

1. **Per-filename allowlist scoping** -- if reviewers begin returning
   findings about artifacts outside their designated scope (drift), extending
   `PhaseBinding` with a `reviewer_scope: tuple[str, ...]` field is the
   natural fix. Not implemented because drift has not been observed.

2. **ESCALATED finding resolution** -- when a producer escalates via
   `koan_ask_question`, the user's reply determines whether to loop back to
   the phase start or accept a modified approach. The current implementation
   relies on the producer to re-run the write step after the user's direction;
   no explicit re-run hook is enforced.
