# Artifact lifecycle and persistence contract

Artifacts are markdown files that the orchestrator writes into the run directory
(`~/.koan/runs/<id>/`). They carry information between phases and, in some cases,
from phases to executor subagents. This document is the authoritative source of
truth for artifact lifetime, frontmatter shape, the artifact write tool, and the
section structure each artifact must contain.

---

## Lifetime taxonomy

Artifacts fall into three lifetime classes:

**Frozen** -- written once, never re-written after the producing phase exits.
The content is stable for the remainder of the run. Downstream phases read it
but must not write it. Example: `brief.md` (produced by intake, read by all
subsequent phases and executor handoffs).

**Additive-forward** -- rewritten across the run, but outcome sections are
append-only once written. History stays visible in the file; earlier sections
are never deleted or overwritten. Example: `milestones.md` (created by
milestone-spec, updated by exec-review after each milestone completes).

**Disposable** -- written once by a producing phase, consumed by one or more
downstream phases, then superseded. Once the downstream work is done, the file
is no longer authoritative. Its content is compressed into a downstream artifact
(e.g., the completed milestone Outcome in `milestones.md`). Examples:
`plan.md`, `plan-milestone-N.md`.

---

## Per-artifact lifecycle table

| Artifact              | Lifetime         | Producer phase(s)                                 | Reader phase(s)                                                                                                                                                      | Final-status timing                                                |
| --------------------- | ---------------- | ------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| `brief.md`            | frozen           | `intake`                                          | `milestone-spec`, `milestone-review`, `plan-spec`, `plan-review`, `exec-review`, `curation`; executor (via handoff)                                                  | `Final` at intake exit                                             |
| `core-flows.md`       | frozen           | `core-flows`                                      | `tech-plan-spec`, `tech-plan-review`, `milestone-spec`, `milestone-review`, `plan-spec`, `plan-review`, `exec-review`; executor (via handoff in initiative workflow) | `Final` at core-flows exit                                         |
| `tech-plan.md`        | disposable       | `tech-plan-spec`                                  | `tech-plan-review`, `milestone-spec`, `milestone-review`, `plan-spec`, `plan-review`, `exec-review`; executor (via handoff in initiative workflow)                   | `Final` at tech-plan-review exit                                   |
| `milestones.md`       | additive-forward | `milestone-spec` (CREATE), `exec-review` (UPDATE) | all milestone phases; executor (via handoff)                                                                                                                         | `In-Progress` until last milestone done; `Final` after last UPDATE |
| `plan.md`             | disposable       | `plan-spec`                                       | `plan-review`, `execute`, `exec-review`                                                                                                                              | `Final` at plan-spec exit                                          |
| `plan-milestone-N.md` | disposable       | `plan-spec`                                       | `plan-review`, `execute`, `exec-review`                                                                                                                              | `Final` at plan-spec exit                                          |

Note: M2-M6 introduce the producers and readers listed in the table. M1 only
documents the contract; the tools that enforce it land in later milestones.

The `frame` phase produces no artifact; the discovery workflow's exit is
negotiated with the user and writes nothing unless the user explicitly
directs an artifact shape at exit. Frame is therefore not listed in this
table.

---

## Per-artifact section structure

This section is the structural reference for each artifact. It pins which
sections must appear, in what order, and what each section answers. The
authoritative source for the LLM-facing prompt remains the phase module's
`PHASE_ROLE_CONTEXT` and step guidance; this section summarizes the contract
for readers who need the artifact shape without reading every phase module.
When the prompt and this section disagree, the prompt wins. Update both when
either changes.

For artifacts that include rendered diagrams, the diagram-slot details
(diagram type, suppression thresholds, grounding rules, level-separation
rules) are owned by `docs/visualization-system.md` and are not duplicated
here. Diagram-bearing entries below reference that doc by section.

### `brief.md`

Title format: `# <Initiative title>`.

Required sections, in order:

1. **Initiative** -- one paragraph restating the user's task in refined
   wording.
2. **Scope** -- contains two subsections: `### In scope` and `### Out of
   scope`. Out-of-scope matters more than in-scope because it prevents
   downstream scope growth.
3. **Affected subsystems** -- concrete file paths and modules with one-line
   descriptions, grounded in real code structure (verified during intake's
   Deepen step).
4. **Decisions** -- numbered list. For each decision: the choice made, the
   rejected alternatives, and the rationale. Each decision is a constraint
   downstream plans must respect.
5. **Constraints** -- cross-cutting (technical, architectural, operational)
   boundaries the executor must respect.
6. **Assumptions** -- explicit list of things assumed without verifying, so
   they are falsifiable if execution reveals them wrong.
7. **Open questions** -- caution zones for downstream phases (questions
   surfaced during intake but not resolved).

Structural rules:

- If a section has no content, write `(none)` under its heading. Do NOT omit
  sections -- downstream phases parse the structure and rely on every section
  being present.

Source of truth: `koan/phases/intake.py:step_guidance(3)`.

### `core-flows.md`

Title format: `# Core Flows`.

Sections: one per flow, each named `## Flow N: <title>`. The number of flows
is discovered during the phase; the artifact has no fixed flow count.

Per-flow content:

- Either a mermaid `sequenceDiagram` block (the SEQ slot from
  `visualization-system.md` §4) **or** the suppression marker comment
  `<!-- diagram suppressed: below complexity threshold -->` when the flow has
  2 actors AND fewer than 4 messages AND no branching.
- A step narrative covering: trigger (what initiates the flow), the sequenced
  steps in order, and exit conditions (success, failure, timeout).

Structural rules:

- No file paths, no component names, no implementation detail. The artifact
  describes operational behavior, not internal structure.
- SEQ diagrams only. No CMP, CON, or STT diagrams in this artifact.
- Grounding: every actor in any diagram must trace to a named concept in
  `brief.md` or the dialogue that preceded the phase. No invented actors.

Source of truth: `koan/phases/core_flows.py:PHASE_ROLE_CONTEXT`.

Diagram contract: `visualization-system.md` §3 (SEQ row), §4 (slot mapping),
§5 (suppression thresholds), §6 (grounding rule).

### `tech-plan.md`

Title format: `# Technical Plan`.

Required sections, in order:

1. **Architectural Approach** -- the high-level structural strategy. Contains
   a CON slot (`flowchart` Container view showing runtime processes,
   services, and data stores) plus prose: chosen path and rejected
   alternatives with rationale.
2. **Data Model** -- schemas for the entities introduced or modified,
   rendered as fenced code blocks. NOT ER diagrams.
3. **Component Architecture** -- internal structure per container. Contains
   one CMP slot per container (`classDiagram` or `flowchart` showing
   components within that container). Cross-component flows use SEQ slots
   (`sequenceDiagram`); per-entity lifecycles use STT slots
   (`stateDiagram-v2`) when warranted.

Structural rules:

- Each section MUST express the chosen path and the rejected alternatives
  with rationale. The reviewer phase (`tech-plan-review`) needs explicit
  alternatives to stress-test against.
- No per-file or per-function implementation steps. That is `plan-spec`'s
  job; tech-plan describes structure, not implementation steps.
- Grounding: every node, actor, and state in any diagram must trace to a
  named concept in `brief.md`, `core-flows.md`, or codebase analysis notes
  from this run.
- Level-separation: no cross-level mixing within a single diagram. CON
  diagrams show containers, not components. CMP diagrams show components
  within one container, not other containers. SEQ diagrams show messages
  between identified actors, not internal component calls.
- Below-threshold slots are rendered as prose with the suppression marker
  comment `<!-- diagram suppressed: below complexity threshold -->`.

Source of truth: `koan/phases/tech_plan_spec.py:PHASE_ROLE_CONTEXT`.

Diagram contract: `visualization-system.md` §3 (CON, CMP, SEQ, STT rows), §4
(slot mapping), §5 (suppression thresholds), §6 (grounding rule), §7
(anti-patterns including level-separation).

### `milestones.md`

Title format: `# Milestones: <initiative title>`.

Sections: one per milestone, each named `## Milestone N: <title> [status]`.
Status markers are `[pending]`, `[in-progress]`, `[done]`, `[skipped]`.

Per-milestone content:

- **Body**: 1--6 sentence sketch of what the milestone covers. Sketches
  longer than 6 sentences indicate the milestone is doing too much and
  should be split.
- **`### Outcome`** subsection (only for `[done]` milestones). Contains four
  sub-sub-sections, in order:
  1. **Integration points** -- interfaces created, files touched.
  2. **Patterns** -- conventions established by this milestone that later
     milestones should follow.
  3. **Constraints discovered** -- constraints that emerged during execution
     and affect later milestones.
  4. **Deviations from plan** -- what differed from `plan-milestone-N.md`,
     and why.

Ownership split:

- `milestone-spec` (CREATE mode) writes the initial sketches with `[pending]`
  status. (RE-DECOMPOSE mode revises pending and in-progress milestones; it
  must preserve all `[done]` milestones and their Outcome sections intact.)
- `exec-review` owns the status transition to `[done]` and the Outcome
  authoring (M4 design). `milestone-spec` does NOT mark milestones `[done]`
  and does NOT write Outcome sections.

Structural rules:

- Status markers MUST appear in brackets after the milestone title and MUST
  be one of the four allowed values.
- Once an `### Outcome` is written for milestone N, every subsequent write
  of `milestones.md` MUST preserve it intact. The artifact is
  additive-forward.

Source of truth (sketch format): `koan/phases/milestone_spec.py:PHASE_ROLE_CONTEXT`.
Source of truth (Outcome authoring and status transitions):
`koan/phases/exec_review.py`.

### `plan.md` and `plan-milestone-N.md`

Title format: `# Plan: <task or milestone title>` (loose convention; the
artifact's content carries the contract, not the title).

Required sections, in order:

1. **Approach summary** -- 2--4 sentences on the overall implementation
   strategy.
2. **Key decisions** -- numbered list of architectural and design decisions
   made during planning.
3. **Implementation steps** -- numbered list. Each step gives a file path, a
   function/location, and the exact change. Be specific: include function
   signatures and type names where relevant.
4. **Constraints** -- hard boundaries the executor must respect.
5. **Verification** -- how to verify the implementation is correct.

Structural rules:

- Every function the plan introduces or modifies MUST include a docstring
  directive at the relevant Implementation step (or the language's
  idiomatic equivalent -- e.g., a JSDoc block above a TypeScript function).
  The directive cannot be only buried in a global rule; it must be visible
  at the step that introduces or changes the function.
- The plan MUST reference actual file paths and function names from the
  codebase. No invented paths or names.
- The plan writes instructions for an executor, not code.

Filename convention: `plan.md` in plan workflows; `plan-milestone-N.md` in
milestones-style workflows where N is the current `[in-progress]`
milestone's number.

Source of truth: `koan/phases/plan_spec.py:PHASE_ROLE_CONTEXT`.

---

## Frontmatter convention

Every artifact written by `koan_artifact_write` has
a YAML frontmatter block prepended by the driver:

```
---
status: In-Progress
created: 2026-04-26T12:34:56.789012+00:00
last_modified: 2026-04-26T12:34:56.789012+00:00
---
```

Frontmatter rules:

- **Driver-managed, LLM-invisible.** The LLM never sees or writes frontmatter.
  `koan_artifact_view` strips it before returning the body to the caller.
  `koan_artifact_list` exposes `status` per file for frontend and projection use.
- **Fields**: `status` (string), `created` (ISO-8601 UTC), `last_modified`
  (ISO-8601 UTC). Field order is stable (`status`, `created`, `last_modified`).
- **First write**: `status` defaults to `In-Progress`; `created` and
  `last_modified` are both set to the write timestamp.
- **Subsequent writes**: `created` is preserved; `last_modified` is updated;
  `status` is preserved unless the caller passes an explicit value.
- **Migration**: artifacts written before M1 have no frontmatter. On the next
  write, frontmatter is attached; `created` is set to the migration timestamp
  (the original creation moment is unrecoverable).
- **Parse failure**: if an existing file has malformed frontmatter (no closing
  `---` delimiter or invalid YAML), the driver logs a warning, treats the file
  as having no frontmatter, and overwrites with valid frontmatter on the next
  write.

---

## Status taxonomy

Four values, defined in `koan/artifacts.py:STATUS_VALUES`:

| Status        | Meaning                                                 |
| ------------- | ------------------------------------------------------- |
| `Draft`       | Work in progress; not ready for downstream consumption. |
| `In-Progress` | Default for first write. Active but not yet complete.   |
| `Approved`    | Reviewed and accepted; downstream phases may proceed.   |
| `Final`       | Producing phase has exited; content is stable.          |

Precise per-artifact transition rules are settled in M4. M1 establishes the
vocabulary and the `In-Progress` default.

---

## Write tool

**`koan_artifact_write(filename, content, status?)`** -- the only
artifact-write tool. Writes the file (full-rewrite semantics) and returns
immediately with `{"ok": true, "filename": ..., "status": ...}`. Emits
`artifact_diff` events for the sidebar. Use this for every artifact mutation.
The `status` argument is optional; defaults to `In-Progress` on first write
and preserves the existing status on subsequent writes unless explicitly
overridden.

The legacy `koan_artifact_propose` tool was retired in M5 (commit `99a4e29`)
along with the inline-review frontend surface (M6, commit `1670f06`).
Artifact-acceptance is no longer surface-gated; the structural pattern in
current workflows is rewrite-or-loop-back in the producer-validator phase pair,
with the user's phase-switch decision after the validator's yield serving as
the implicit acceptance moment.
