# Artifact lifecycle and persistence contract

Artifacts are markdown files that the orchestrator writes into the run directory
(`~/.koan/runs/<id>/`). They carry information between phases and, in some cases,
from phases to executor subagents. This document is the authoritative source of
truth for artifact lifetime, the artifact read/write/edit tools, and the
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
`milestone`, updated by `execute` after each milestone completes).

**Disposable** -- written once by a producing phase, consumed by one or more
downstream phases, then superseded. Once the downstream work is done, the file
is no longer authoritative. Its content is compressed into a downstream artifact
(e.g., the completed milestone Outcome in `milestones.md`). Examples:
`plan.md`, `plan-milestone-N.md`.

---

## Per-artifact lifecycle table

| Artifact                 | Lifetime         | Producer phase(s)                                                         | Reader phase(s)                                                                            |
| ------------------------ | ---------------- | ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| `brief.md`               | frozen           | `intake`                                                                  | `milestone`, `plan`, `execute`, `curation`; executor (via handoff)                         |
| `core-flows.md`          | frozen           | `core-flows`                                                              | `tech-plan`, `milestone`, `plan`, `execute`; executor (via handoff in initiative workflow) |
| `tech-plan.md`           | disposable       | `tech-plan`                                                               | `milestone`, `plan`, `execute`; executor (via handoff in initiative workflow)              |
| `milestones.md`          | additive-forward | `milestone` (CREATE), `execute` (UPDATE)                                  | `milestone`, `plan`, `execute`, `curation`; executor (via handoff)                         |
| `plan.md`                | disposable       | `plan`                                                                    | `execute`; executor (via handoff)                                                          |
| `plan-milestone-N.md`    | disposable       | `plan`                                                                    | `execute`; executor (via handoff)                                                          |
| `<reviewable>.review.md` | sidecar          | koan (reviewer findings); orchestrator (appends disposition + exec notes) | `execute` (post-exec inline review); orchestrator during remediation                       |

Note: M2-M6 introduce the producers and readers listed in the table. M1 only
documents the contract; the tools that enforce it land in later milestones.

The `frame` phase produces no artifact; the discovery workflow's exit is
negotiated with the user and writes nothing unless the user explicitly
directs an artifact shape at exit. Frame is therefore not listed in this
table.

---

## Per-step write and freeze contract

The lifecycle table above maps each artifact to its producing _phase_. This
section refines that to the _step_ level: the single step in which each artifact
may be created, the steps in which it may be edited, and the step at which it
becomes read-only.

**Why step-level.** The artifact registry (`koan/tools/artifact_registry.py`)
carries `origin_phases` per family and rejects an out-of-phase write with
`wrong_phase`; freeze is folded from `execute_entry` events. Within a producing
phase, a per-step layer is now also enforced: `ArtifactRegistryEntry` carries
`create_steps` / `edit_steps` (sets of `(phase, step_name)` pairs, with
`origin_phases` derived from `create_steps`), and `validate_write` /
`validate_edit` consult the current step name (resolved from the phase module's
`STEP_NAMES` at the tool-call site), rejecting an out-of-step call with the
`out_of_step` code. The prompt-level "do not write" guards in intake steps 1-2
(see [prompt-system.md](./prompt-system.md) `blk.no-writes`) are now advisory --
they prevent the mistake up front; the gate is the hard backstop.

Steps are named (`phase.N Name`); phases get restructured but named steps are stable.

| Artifact                          | Created in              | Editable in                                                                                       | Becomes read-only at                                                   |
| --------------------------------- | ----------------------- | ------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| `brief.md`                        | `intake.3` Summarize    | `intake.3` only (revise before exit)                                                              | intake exit                                                            |
| `core-flows.md`                   | `core-flows.2` Write    | `core-flows.2`                                                                                    | core-flows exit                                                        |
| `tech-plan.md`                    | `tech-plan.2` Write     | `tech-plan.2` (reviewer reconcile)                                                                | tech-plan exit (disposable)                                            |
| `milestones.md`                   | `milestone.2` Write     | `milestone.2` (reviewer reconcile); `execute.2` Assess (CLEAN UPDATE)                             | never -- additive-forward; discarded + recreated on milestone re-entry |
| `plan.md` / `plan-milestone-N.md` | `plan.2` Write          | `plan.2` (reviewer reconcile)                                                                     | the execute handoff at the end of `plan.2` (`execute_entry` freeze)    |
| `*-remediation-K.md`              | `plan.2` (see note)     | `plan.2`                                                                                          | the re-execute handoff                                                 |
| `<stem>.review.md` (sidecar)      | koan, on reviewer write | disposition append in `tech-plan.2` / `milestone.2` / `plan.2`; exec-review append in `execute.2` | never (freeze-exempt)                                                  |

### Notes

- **First write wins (the draft trap).** A created artifact cannot be re-`write`n:
  a second `koan_artifact_write` to an existing draft is now rejected recoverably --
  the tool returns `{"ok": false, "error": {"reason": "exists_draft", ...}}` (it no
  longer raises); the agent self-corrects by using `koan_artifact_edit`. But a
  premature create is still _destructive_ if it lands -- the legitimate later write
  would fail and the bad early draft would survive. That is what the per-step gate
  prevents.

- **Cross-phase edits are legitimate and must be allowed.** `milestones.md` is
  created in `milestone.2` but edited in `execute.2` (the CLEAN-path UPDATE); the
  `.review.md` sidecar is appended in four different steps. A per-step `editable`
  set is therefore a list, not a single step.

- **The remediation flow straddles a phase boundary (resolved).** `execute.2`'s
  NON-CONFORMING base path calls `koan_set_phase("plan")` and _then_ writes
  `*-remediation-K.md`. This is now legal: the plan family's `create_steps` /
  `edit_steps` include both `(plan, Analyze)` and `(plan, Write)`, so the
  post-transition write (which fires while the re-entered `plan` phase is at its
  Analyze step) passes the per-step gate.

### Enforcement (implemented)

`ArtifactRegistryEntry` carries `create_steps` / `edit_steps` (sets of
`(phase, step_name)` pairs); `origin_phases` is derived from `create_steps`.
At each tool-call site, the current step name is resolved from
`phase_module.STEP_NAMES` and passed to `validate_write(step_name=)` /
`validate_edit(phase=, step_name=)`. A call arriving in the wrong step is
rejected with the `out_of_step` code, which carries an `allowed` hint listing
the legal (phase, step) pairs so the agent can self-correct. The per-step check
is fail-open when the step name cannot be resolved. Sidecars (`.review.md`) are
exempt from per-step gating (as well as from freeze). Freeze is unchanged
(folded from `execute_entry` events).

Recoverable validation failures -- `out_of_step`, `wrong_phase`, `exists_draft`,
`exists_frozen`, `chain_gap`, `frozen`, and the transition codes from
`koan_set_phase` / `koan_set_workflow` / the execute-handoff
`validate_execute_target` check -- are returned to the agent as the
`{"ok": false, "error": {"reason": ..., "message": ..., "allowed": ...,
"suggested_name": ...}}` envelope (never raised). Only genuine infrastructure
faults (`no_run_dir`, `invalid_path`, `write_failed`, `edit_failed`) raise.
The agent receives the corrective message and retries; the gate never crashes
the run.

### Why reject in the wrong step, not hide the tool

Enforcement must be a runtime **rejection** (`out_of_step` error), not removal of
the tool from the agent's context -- and the reason is prompt caching. Tool
definitions live in the agent's system-prompt prefix, which is the cached portion
of every request. The construction-time default-deny composes the toolset once per
`(role, phase)` (`compose_toolset` in `koan/tools/tool_policy.py`) precisely so the
tool-definition prefix stays byte-stable across every step within a phase -- the
cache survives the whole phase. If we instead added or removed tools per step to
express per-step capability, the prefix would change at every step boundary and
invalidate the cache each time, paying a full prompt re-process cost on every step.

So the tool stays visible for the entire phase; calling it in a step where it is
not yet legal returns an error the agent can recover from. **Per-step capability is
a property of the call validator, never of the exposed toolset.** (Phase-level
capability can still be expressed by composition, because the toolset is rebuilt at
the phase boundary anyway, where a cache miss is unavoidable.)

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
  `visualization-system.md` §4) **or** plain prose only (no marker, no
  placeholder) when the flow has 2 actors AND fewer than 4 messages AND no
  branching.
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
  with rationale. The mechanical TECH_PLAN_REVIEWER sub-agent needs explicit
  alternatives to stress-test against.
- No per-file or per-function implementation steps. That is `plan`'s
  job; tech-plan describes structure, not implementation steps.
- Grounding: every node, actor, and state in any diagram must trace to a
  named concept in `brief.md`, `core-flows.md`, or codebase analysis notes
  from this run.
- Level-separation: no cross-level mixing within a single diagram. CON
  diagrams show containers, not components. CMP diagrams show components
  within one container, not other containers. SEQ diagrams show messages
  between identified actors, not internal component calls.
- Below-threshold slots are rendered as prose only. Do NOT emit a marker
  comment or placeholder -- the prose alone is the slot.

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

- `milestone` (CREATE mode) writes the initial sketches with `[pending]`
  status. Re-decomposition discards the stale `milestones.md` automatically
  on `milestone` re-entry (discard-hook + fresh CREATE); all `[done]`
  milestones and their Outcome sections are preserved in the frozen/executed
  plan history.
- `execute` owns the status transition to `[done]` and the Outcome authoring
  (inline conformance review pass). `milestone` does NOT mark milestones
  `[done]` and does NOT write Outcome sections.

Structural rules:

- Status markers MUST appear in brackets after the milestone title and MUST
  be one of the four allowed values.
- Once an `### Outcome` is written for milestone N, every subsequent write
  of `milestones.md` MUST preserve it intact. The artifact is
  additive-forward.

Source of truth (sketch format): `koan/phases/milestone_spec.py:PHASE_ROLE_CONTEXT`.
Source of truth (Outcome authoring and status transitions):
`koan/phases/execute.py` (step 2, Assess -- the inline conformance review;
`exec_review.py` was removed in the M6 review collapse).

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

## Plain files (no frontmatter)

Artifacts are **plain markdown files** in the run directory. They carry no
driver-managed frontmatter: `koan_artifact_write` writes the body verbatim.
Listing metadata (size, modified time) comes from the filesystem
(`list_artifacts`), not from any embedded block.

> History: artifacts previously embedded a YAML `created`/`last_modified`
> frontmatter block that the tools stripped on read. Nothing outside the tools
> consumed it (the sidebar uses filesystem mtime/size), so it was dropped when
> the artifact tools became thin wrappers over `read`/`write`/`edit`.

---

## Read, write, and edit tools

The artifact tools are **run-dir-scoped wrappers** over the built-in
`read`/`write`/`edit` (see [tools.md](./tools.md)). They give planning roles a
file interface limited to their run directory's artifacts -- the orchestrator
can produce and revise artifacts but cannot write/edit arbitrary project files.
Each wrapper adds filename validation, run-dir containment, and (for
write/edit) the `artifact_diff` projection event.

**`koan_artifact_write(filename, content)`** -- full rewrite. Writes the body
verbatim and returns `{"ok": true, "filename": ...}`. Emits `artifact_diff`.
Use it to create an artifact or replace it wholesale. Permission failures
(wrong phase, wrong step, existing draft, frozen) are returned as
`{"ok": false, "error": {"reason": ..., "message": ..., ...}}` so the agent
can self-correct; only infrastructure faults (`no_run_dir`, `invalid_path`,
`write_failed`) raise.

**`koan_artifact_read(filename, offset?, limit?)`** -- returns anchored,
line-numbered content (`{lineno}\t{anchor}§{line}`). Copy an anchor into
`koan_artifact_edit`; page large artifacts with `offset`/`limit` for
convenience. `koan_artifact_read` is **trusted and exempt** from the untrusted
reject ceiling: it calls `read_tool(..., enforce_limits=False)` and returns
large artifacts in full with no hard reject. Error: `not_found`.

**`koan_artifact_edit(filename, anchor, text, end_anchor?, edit_type?)`** --
anchored line edit (see the hash-anchored protocol in [tools.md](./tools.md)).
`edit_type` is `replace` (default), `insert_before`, or `insert_after`; an
inclusive range replace uses `end_anchor`; empty `text` deletes. Returns
`{"ok": true, "filename": ...}`. Permission failures (wrong phase, wrong step,
frozen) are returned as `{"ok": false, "error": {"reason": ..., "message": ...,
...}}` so the agent can self-correct. Infrastructure faults raise: `not_found`
(file missing), `edit_failed` (anchor not found, content drift, or bad
edit_type). Preferred for targeted in-place fixes; `koan_artifact_write` for
extensive rewrites.

The legacy `koan_artifact_propose` tool was retired in M5 (commit `99a4e29`)
along with the inline-review frontend surface (M6, commit `1670f06`).
Artifact-acceptance is no longer surface-gated; the structural pattern in
current workflows is rewrite-or-loop-back in the producer-validator phase pair,
with the user's phase-switch decision after the validator's yield serving as
the implicit acceptance moment.
