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

The producer appends a per-finding disposition to the `.review.md` sidecar
so the finding record is preserved alongside the artifact.

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
sidecar record reflects why the finding was dismissed.

## Per-phase responsibilities

### intake (3 steps: Gather, Deepen, Summarize)

- Explores the codebase, asks the user targeted questions, resolves ambiguity.
- Writes `brief.md` (frozen after intake).
- Downstream phases trust intake's findings as their starting point.
- No mechanical reviewer; `brief.md` is final at exit.

### milestone (2 steps: Analyze, Write) -- milestones workflow only

- CREATE-only semantics: decomposes the initiative into milestones grounded
  in code structure.
- On milestone re-entry (loop-back after one or more milestones have been
  executed), a discard hook fires on phase entry and deletes non-frozen,
  non-executed artifacts from the run directory, so the producer starts
  from a clean slate for the revised decomposition.
- MUST NOT mark milestones `[done]` or add Outcome sections -- the execute
  phase's deviation report and the orchestrator's post-execute bookkeeping
  own those transitions.
- Writing `milestones.md` triggers the MILESTONE_REVIEWER. Producer
  reconciles findings inline.

### plan (2 steps: Analyze, Write)

- Reads codebase files to write precise implementation instructions.
- In milestones workflow: scoped to the current `[in-progress]` milestone.
  Produces `plan-milestone-N.md`. Reads prior milestone Outcome sections for
  integration points, patterns, and constraints established by prior
  milestones.
- In plan workflow: produces `plan.md`.
- Writing the plan artifact triggers the PLAN_REVIEWER. Producer reconciles
  findings inline.

### execute (1 step: Implement)

- Entered via `koan_set_phase("execute", plan_file=X)` from the orchestrator.
- This call freezes the named plan, spawns the executor sub-agent, and
  returns a deviation report as the tool result when the executor exits.
- The orchestrator reads the deviation report and determines the next phase:
  - Significant deviations: loop back to `plan` for re-work.
  - Clean execution or minor deviations: advance toward `curation` or the
    next milestone.
  - Milestones workflow: mark the completed milestone `[done]`, append the
    four-subsection Outcome, advance the next `[pending]` milestone to
    `[in-progress]`, then yield with the next-phase suggestion.

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
|                   | toolset unconditionally via `compose_toolset`           |
| Prompt discipline | Each phase is instructed to edit only its own artifact |
| Reviewer role     | `reviewer` role has no write tools; read-only          |

The reviewer sub-agent is restricted by construction: it receives only
`Read`, `Bash`, `Glob`, and `Grep` built-in tools and no koan write
tools. It cannot modify the artifact it reviews; it can only return
findings. The producer holds the write capability and makes all
editorial decisions.

## Data flow: plan workflow

```
brief.md (frozen, written by intake)
    |
    v
plan ----> plan.md
    |      koan_artifact_write triggers PLAN_REVIEWER (blocking)
    |      producer reconciles inline, edits plan.md, appends to plan.review.md
    v
koan_set_phase("execute", plan_file="plan.md")
    |      freezes plan.md, spawns executor sub-agent
    |      returns deviation report when executor exits
    v
orchestrator reads deviation report:
    |  -- significant deviations: hand back (suggest plan loop-back)
    |  -- clean: hand back (suggest curation)
    v
curation
```

## Data flow: milestones workflow

```
brief.md (frozen, written by intake)
    |
    v
milestone (CREATE) ----> milestones.md
    |      koan_artifact_write triggers MILESTONE_REVIEWER (blocking)
    |      producer reconciles inline, edits milestones.md,
    |      appends to milestones.review.md; yields with "plan" suggested
    v
plan ----> plan-milestone-N.md   (reads prior Outcome sections)
    |      koan_artifact_write triggers PLAN_REVIEWER (blocking)
    |      producer reconciles inline; yields with "execute" suggested
    v
koan_set_phase("execute", plan_file="plan-milestone-N.md")
    |      freezes plan, spawns executor sub-agent
    |      returns deviation report when executor exits
    v
orchestrator reads deviation report:
    |      -- mark completed [done], append four-subsection Outcome
    |      -- advance next [pending] -> [in-progress]
    |      -- adjust remaining sketches if deviations require it
    |
    +---> [if milestones remain] hand back (suggest plan) -> LOOP
    |
    +---> [if all done/skipped] hand back (suggest curation)
    |
    +---> [if graph needs revision] hand back (suggest milestone)
         (discard hook fires on milestone re-entry)
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
