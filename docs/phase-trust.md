# Phase Trust Model

Design decision document for how phases relate to each other's outputs and
how review phases apply rewrite-or-loop-back semantics to producer artifacts.

## Principle

Review phases apply **rewrite-or-loop-back** semantics. For each finding, the
reviewer classifies it as internal or new-files-needed; internal findings are
fixed in place by issuing `koan_artifact_write` against the producer's artifact;
new-files findings surface at the phase-boundary hand-back with the producer
phase recommended.

All other phases trust the chain. Re-verification outside designated review
phases is the "intrinsic self-correction" anti-pattern and is explicitly
rejected in this project.

## Why the model changed

Before M4, review phases were report-only: findings were reported in chat and
the artifact was not modified. The producer phase re-ran the entire decomposition
or plan to incorporate fixes. This caused unnecessary round-trips: most findings
are internal mistakes the producer should have caught from the files it already
loaded. Routing every finding through a full producer-phase re-run was wasteful
for the common case.

The M4 change applies the principle of fixing locally what can be fixed locally.
The round-trip to the producer phase is reserved for findings that genuinely
require new information the producer did not have.

## The classification rule

For each finding, the reviewer judges: **could the producer have caught this
given the files the producer already loaded?** The producer's loaded context is:
- The artifact body it wrote (plan.md, milestones.md, plan-milestone-N.md)
- `brief.md` (the frozen initiative scope, decisions, and constraints)

If yes -> **internal** -> fix in place via `koan_artifact_write`.

If no (catching this would require loading files the producer did not open) ->
**new-files-needed** -> surface at the phase-boundary hand-back with the
producer phase recommended. The producer re-runs with the new files in scope.

Mixed: fix internal findings in place AND recommend loop-back for the
new-files findings. The producer sees the partially-rewritten artifact plus
the outstanding findings.

## Per-phase responsibilities

### intake (3 steps: Gather, Deepen, Summarize)

- Explores the codebase, asks the user targeted questions, resolves ambiguity.
- Writes `brief.md` with status="Final" (frozen after intake).
- Downstream phases trust intake's findings as their starting point.
- Does NOT apply rewrite-or-loop-back (not a review phase).

### milestone-spec (2 steps: Analyze, Write) -- milestones workflow only

- Two modes: **CREATE** (milestones.md does not exist) and **RE-DECOMPOSE**
  (milestones.md exists and the user explicitly redirected here).
- CREATE: decomposes the initiative into milestones grounded in code structure.
- RE-DECOMPOSE: revises `[pending]` / `[in-progress]` milestone sketches when the
  milestone graph itself needs to change (not routine post-execution bookkeeping).
- Routine UPDATE work (mark `[done]`, append Outcome, advance next `[pending]`)
  has moved to exec-review.
- MUST preserve all `[done]` milestones and their Outcome sections intact in
  RE-DECOMPOSE mode.
- MUST NOT mark milestones `[done]` or add Outcome sections -- exec-review owns
  those transitions.

### milestone-review (2 steps: Read, Evaluate) -- milestones workflow only

- The designated adversarial verifier for milestone decomposition.
- **Applies rewrite-or-loop-back** against `milestones.md`:
  - Internal findings -> `koan_artifact_write(filename="milestones.md", ...)`
  - New-files findings -> hand back with `milestone-spec` recommended
- When rewriting, MUST preserve all `[done]` Outcome sections intact.
- **Compound-risk framing**: a missed issue here is inherited by every
  subsequent plan-spec and executor session.

### plan-spec (2 steps: Analyze, Write)

- Reads codebase files to write precise implementation instructions.
- In milestones workflow: scoped to the current `[in-progress]` milestone.
  Produces `plan-milestone-N.md`. Reads prior milestone Outcome sections for
  integration points, patterns, and constraints established by prior milestones.
- In plan workflow: produces `plan.md`.
- Does NOT apply rewrite-or-loop-back (not a review phase).

### plan-review (2 steps: Read, Evaluate)

- The designated adversarial verifier for implementation plans. Trusts nobody.
- **Applies rewrite-or-loop-back** against the plan artifact:
  - Internal findings -> `koan_artifact_write(filename="<plan_artifact>", ...)`
  - New-files findings -> hand back with `plan-spec` recommended
- Plan artifact filename: `plan.md` in plan workflow; `plan-milestone-N.md` in
  milestones workflow.

### exec-review (2 steps: Verify, Assess)

- The designated verifier for execution results. Trusts nobody -- not the plan,
  not the executor's self-report.
- Runs verification commands (build, tests, type checks) to confirm executor claims.
- **Applies rewrite-or-loop-back** against the plan artifact (same rule as
  plan-review; clean executions skip this step entirely).
- **Milestones workflow only -- applies milestones.md UPDATE**:
  1. Mark the completed milestone `[done]`.
  2. Append `### Outcome` with four subsections:
     - **Integration points created** -- new interfaces, extension seams, modules
       subsequent milestones can depend on.
     - **Patterns established** -- naming, file placement, error handling, and
       test conventions this milestone committed to.
     - **Constraints discovered** -- things harder/different than the sketch
       anticipated; explicit facts that change what future milestones can assume.
     - **Deviations from plan** -- what the executor did differently and why.
  3. Advance the next `[pending]` milestone to `[in-progress]`.
  4. Adjust remaining milestone sketches if deviations require it.
  5. Preserve all prior `[done]` Outcome sections intact.
  Issues `koan_artifact_write(filename="milestones.md", ...)` for the UPDATE.
  Plan-workflow exec-review skips the UPDATE entirely (no milestones.md).

### execute (2 steps: Compose, Request)

- Composes the executor handoff from the plan artifact and plan-review findings.
- Trusts the plan (it has been reviewed). Does not re-evaluate.
- Does NOT apply rewrite-or-loop-back (not a review phase).

## Permission model

The permission model uses **role-level grant + prompt discipline**:

| Layer               | Mechanism                                             |
|---------------------|-------------------------------------------------------|
| Role-level grant    | `koan_artifact_write` composed into the `orchestrator`|
|                     | toolset unconditionally via `compose_toolset`          |
| Prompt discipline   | Each review phase is instructed to rewrite only       |
|                     | its own producer's artifact                           |
| Per-filename scoping| Rejected as over-engineering; no evidence of drift;   |
|                     | simpler design; maintenance cost without proportionate|
|                     | benefit                                               |

The orchestrator role covers all review phases (plan-review, milestone-review,
exec-review). The M1 grant is sufficient. Adding a `write_allowlist` field to
`PhaseBinding` was considered and rejected; it remains available as a future
enhancement if per-filename drift becomes observed in practice.

## Data flow: plan workflow

```
brief.md (frozen, written by intake)
    |
    v
plan-spec ----> plan.md
    |
    v
plan-review  -- classifies each finding:
    |              internal -> koan_artifact_write(plan.md, corrected)
    |              new-files -> hand back (suggest plan-spec loop-back)
    v
execute ----> koan_request_executor(["brief.md", "plan.md"])
    |
    v
exec-review  -- runs verification commands
    |          -- classifies each deviation:
    |              internal -> koan_artifact_write(plan.md, corrected)
    |              new-files -> hand back (suggest plan-spec)
    |          -- (no milestones.md UPDATE in plan workflow)
    v
curation
```

## Data flow: milestones workflow

```
brief.md (frozen, written by intake)
    |
    v
milestone-spec (CREATE) ----> milestones.md
    |
    v
[milestone-review]  -- classifies each finding:
    |                   internal -> koan_artifact_write(milestones.md, revised)
    |                   new-files -> hand back (suggest milestone-spec)
    v
plan-spec ----> plan-milestone-N.md   (reads prior Outcome sections)
    |
    v
[plan-review]  -- classifies each finding:
    |              internal -> koan_artifact_write(plan-milestone-N.md, corrected)
    |              new-files -> hand back (suggest plan-spec loop-back)
    v
execute ----> koan_request_executor(["brief.md", "plan-milestone-N.md", "milestones.md"])
    |
    v
exec-review  -- runs verification commands
    |          -- rewrite-or-loopback against plan-milestone-N.md
    |          -- milestones.md UPDATE:
    |              mark completed [done]
    |              append four-subsection Outcome
    |              advance next [pending] -> [in-progress]
    |              adjust remaining sketches
    |
    +---> [if milestones remain] hand back (suggest plan-spec) -> LOOP
    |
    +---> [if all done/skipped] hand back (suggest curation)
    |
    +---> [if graph needs revision] hand back (suggest milestone-spec RE-DECOMPOSE)
```

## Open questions

1. **Per-filename allowlist scoping** -- if reviewers begin rewriting artifacts
   outside their designated scope (drift), extending `PhaseBinding` with a
   `write_allowlist: tuple[str, ...]` field is the natural fix. Not implemented
   in M4 because drift has not been observed.

2. **Plan-workflow exec-review rewrite value** -- after execution, the plan has
   been followed (or not); rewriting `plan.md` to reflect what the executor
   should have done does not change the delivered code. The value is forward-
   looking: if the same plan serves as a template for a future change, the
   corrected version is more accurate than the original. Accepted as low-cost
   for potential future benefit.
