# Artifact lifecycle and persistence contract

Artifacts are markdown files that the orchestrator writes into the run directory
(`~/.koan/runs/<id>/`). They carry information between phases and, in some cases,
from phases to executor subagents. This document is the authoritative source of
truth for artifact lifetime, the artifact read/write/edit tools, and the
section structure each artifact must contain.

---

## Artifact model: living documents

Artifacts are **living working surfaces** -- the orchestrator edits them in
place throughout their life. The immutable record is the driver-owned,
append-only event log; the markdown carries the working content, not history.

`brief.md` is the sole write-once artifact: it is created by intake and never
rewritten downstream. All other artifacts may be edited in place from any phase
the orchestrator runs in. Review findings and execution outcomes accrete inside
the artifact by convention (`## Review` and `## Execution N` sections),
preserving the working record inline.

The one structural rule that does apply: **first write wins on creation.**
`koan_artifact_write` to an existing artifact is rejected (`exists_draft`);
use `koan_artifact_edit` for in-place revisions after the initial write.

---

## Per-artifact lifecycle table

| Artifact              | Produced by  | Read by                                                                     |
| --------------------- | ------------ | --------------------------------------------------------------------------- |
| `brief.md`            | `intake`     | `milestone`, `plan`, `execute`, `curation`; executor                        |
| `core-flows.md`       | `core-flows` | `tech-plan`, `milestone`, `plan`, `execute`; executor (initiative workflow) |
| `tech-plan.md`        | `tech-plan`  | `milestone`, `plan`, `execute`; executor (initiative workflow)              |
| `milestones.md`       | `milestone`  | `milestone`, `plan`, `execute`, `curation`; executor                        |
| `plan.md`             | `plan`       | `execute`; executor                                                         |
| `plan-milestone-N.md` | `plan`       | `execute`; executor                                                         |

The `frame` phase produces no artifact; the discovery workflow's exit is
negotiated with the user and writes nothing unless the user explicitly
directs an artifact shape at exit. Frame is therefore not listed in this
table.

---

## Per-step create gate

The lifecycle table above maps each artifact to its producing _phase_. Within
that phase, a per-step create gate is also enforced: `ArtifactRegistryEntry`
carries `create_steps` (a set of `(phase, step_name)` pairs), and
`validate_write` consults the current step name, rejecting an out-of-step
create with the `out_of_step` code. This prevents premature artifact creation
(a bad early draft would block the legitimate later write with `exists_draft`).

The prompt-level "do not write" guards in intake steps 1-2
(see [prompt-system.md](./prompt-system.md) `blk.no-writes`) are advisory --
they prevent the mistake up front; the gate is the hard backstop.

Steps are named (`phase.N Name`); phases may be restructured but named steps
are stable.

| Artifact                          | Created in           | Editable in                                                            |
| --------------------------------- | -------------------- | ---------------------------------------------------------------------- |
| `brief.md`                        | `intake.3` Summarize | `intake.3` only (revise before exit); write-once after intake exits    |
| `core-flows.md`                   | `core-flows.2` Write | `core-flows.2` (reviewer reconcile); write-once after core-flows exits |
| `tech-plan.md`                    | `tech-plan.2` Write  | `tech-plan.2` (reviewer reconcile)                                     |
| `milestones.md`                   | `milestone.2` Write  | any phase (living-doc family -- edit gate relaxed)                     |
| `plan.md` / `plan-milestone-N.md` | `plan.2` Write       | any phase (living-doc family -- edit gate relaxed)                     |

### Notes

- **First write wins (the draft trap).** A created artifact cannot be re-`write`n:
  a second `koan_artifact_write` to an existing draft is rejected recoverably --
  the tool returns `{"ok": false, "error": {"reason": "exists_draft", ...}}` (it
  no longer raises); the agent self-corrects by using `koan_artifact_edit`. A
  premature create is still _destructive_ if it lands, which is what the per-step
  gate prevents.

- **Living-document families (plan, milestones) are edit-gate-exempt.** Plans and
  `milestones.md` may be edited from any phase the orchestrator runs in, so that
  review findings, re-execution adjustments, and milestone bookkeeping can land
  inline. Create-step gating is unchanged -- these artifacts must still originate
  in the right phase.

### Enforcement (implemented)

`ArtifactRegistryEntry` carries `create_steps` / `edit_steps` (sets of
`(phase, step_name)` pairs); `origin_phases` is derived from `create_steps`.
At each tool-call site, the current step name is resolved from
`phase_module.STEP_NAMES` and passed to `validate_write(step_name=)` /
`validate_edit(phase=, step_name=)`. A call arriving in the wrong CREATE step is
rejected with the `out_of_step` code, which carries an `allowed` hint listing
the legal (phase, step) pairs so the agent can self-correct. For living-doc
families, the edit step check is skipped. The per-step check is fail-open when
the step name cannot be resolved.

Recoverable validation failures -- `out_of_step`, `wrong_phase`, `exists_draft`,
and the transition codes from `koan_set_phase` / `koan_set_workflow` / the
`validate_executor_request` check -- are returned to the agent as the
`{"ok": false, "error": {"reason": ..., "message": ..., "allowed": ...,
"suggested_name": ...}}` envelope (never raised). Only genuine infrastructure
faults (`no_run_dir`, `invalid_path`, `write_failed`) raise.
The agent receives the corrective message and retries; the gate never crashes
the run.

### Why reject in the wrong step, not hide the tool

Enforcement must be a runtime **rejection** (`out_of_step` error), not removal of
the tool from the agent's context -- and the reason is prompt caching. Tool
definitions live in the agent's system-prompt prefix, which is the cached portion
of every request. The default-deny composes the toolset once per role (`compose_toolset` in
`koan/tools/tool_policy.py`) so the tool-definition prefix stays byte-stable
across every step and phase -- the cache survives the whole run. Phase-
conditional tools are gated at call time by `phase_gate_message` rather than by
removing them from the vocabulary. If we instead added or removed tools per step
to express per-step capability, the prefix would change at every step boundary
and invalidate the cache each time, paying a full prompt re-process cost on
every step.

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

- `milestone` writes the initial sketches with `[pending]` status (once, at
  milestone phase entry). The milestone phase is one-time; `milestones.md`
  is edited in place thereafter as understanding evolves. Completed milestones
  are preserved by convention; future scope may be adjusted by editing pending
  or not-yet-started milestones.
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
`koan/phases/execute.py` (Reconcile step -- the inline conformance review).

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
Use it to create an artifact or replace it wholesale. For reviewed artifact
families (plan, milestones, tech-plan), the mechanical reviewer sub-agent runs
as a blocking side-effect and its findings are returned inline. Permission
failures (wrong phase, wrong step, existing draft) are returned as
`{"ok": false, "error": {"reason": ..., "message": ..., ...}}` so the agent
can self-correct; only infrastructure faults (`no_run_dir`, `invalid_path`,
`write_failed`) raise.

**`koan_artifact_read(filename, offset?, limit?)`** -- returns anchored,
line-numbered content (`{lineno}\t{anchor}§{line}`). Copy an anchor into
`koan_artifact_edit`; page large artifacts with `offset`/`limit` for
convenience. `koan_artifact_read` is **trusted and exempt** from the untrusted
output cap: it calls `read_tool(..., limit=None)` and returns large artifacts
in full with no hard cap. Error: `not_found`.

**`koan_artifact_edit(filename, anchor, text, end_anchor?, edit_type?)`** --
anchored line edit (see the hash-anchored protocol in [tools.md](./tools.md)).
`edit_type` is `replace` (default), `insert_before`, or `insert_after`; an
inclusive range replace uses `end_anchor`; empty `text` deletes. Returns
`{"ok": true, "filename": ...}`. Permission failures (wrong phase, wrong step)
are returned as `{"ok": false, "error": {"reason": ..., "message": ...,
...}}` so the agent can self-correct; living-doc families are step-gating-exempt
so in-place edits to plans and `milestones.md` always succeed on the permission
check. `edit_failed` (anchor not found, content drift, or bad edit_type) and `not_found`
(file missing) are returned as `{"ok": false, "error": {"reason": ...}}` envelopes
-- recoverable, never raised -- so a mis-copied anchor cannot crash the run. Only
path-resolution faults (`no_run_dir`, `invalid_path`) raise. Preferred for targeted
in-place fixes; `koan_artifact_write` for extensive rewrites.

The legacy `koan_artifact_propose` tool was retired in M5 (commit `99a4e29`)
along with the inline-review frontend surface (M6, commit `1670f06`).
Artifact-acceptance is no longer surface-gated; the structural pattern in
current workflows is rewrite-or-loop-back in the producer-validator phase pair,
with the user's phase-switch decision after the validator's yield serving as
the implicit acceptance moment.

---

## Handover injection

Immutable artifacts are not read on demand -- they are **injected** at phase
entry as `<handoff_artifact name="...">` user messages, pre-seeded into the
agent's `message_history` before the step prompt. This is the enforcement of
the principle: between phases, the handover IS the file.

### Immutable vs living split

| Category  | Families                     | Delivery                                                                    |
| --------- | ---------------------------- | --------------------------------------------------------------------------- |
| Immutable | brief, core-flows, tech-plan | Injected once at the first phase that declares them in `required_artifacts` |
| Living    | plan, milestones             | Listed in the read-on-demand section; read via `koan_artifact_read`         |

`LIVING_DOC_FAMILIES` in `koan/tools/artifact_registry.py` is the canonical
list. `select_immutable_handovers` in `koan/tools/handoff_artifacts.py`
filters any `required_artifacts` tuple against this set before injecting.

### Per-phase required set (initiative workflow)

`PhaseBinding.required_artifacts` in `koan/lib/workflows.py` declares the
cumulative ordered set of immutable filenames each phase consumes. Declaring
the full cumulative set (not just the delta) keeps phase-jump correctness
intact -- the injector deduplicates against `AgentState.injected_artifacts`
so a file injected in a prior phase is never re-injected.

| Phase        | `required_artifacts`                            |
| ------------ | ----------------------------------------------- |
| `core-flows` | `("brief.md",)`                                 |
| `tech-plan`  | `("brief.md", "core-flows.md")`                 |
| `milestone`  | `("brief.md", "core-flows.md", "tech-plan.md")` |
| `plan`       | `("brief.md", "core-flows.md", "tech-plan.md")` |
| `execute`    | `("brief.md", "core-flows.md", "tech-plan.md")` |

In the lighter `plan` and `milestones` workflows, only `brief.md` is declared
immutable; `milestones.md` and per-milestone plans are always living.

### Envelope format

`format_handoff_message(name, content, error=False)` wraps content as:

```
<handoff_artifact name="brief.md">
...content...
</handoff_artifact>
```

The `<handoff_artifact>` envelope is deliberately distinct from
`<project_instructions>` (context-file injection) and from steering envelopes,
so the three message kinds are never conflated. When an I/O fault occurs,
`error="true"` is added to the tag so the agent sees a visible placeholder
rather than a silently empty slot.

### Read-on-demand listing

`build_handover_listing(run_dir, exclude)` produces the "Artifacts available
to read on demand" block appended to the step-1 prompt. It lists every
artifact in the run directory whose filename parses as a valid artifact name
and is not in `exclude` (already-injected plus pending). Because only
immutable families are ever injected, the listing always includes every living
document (`milestones.md`, `plan-milestone-N.md`, `plan.md`).

### Executor and reviewer injection

The same mechanism applies to subagents at spawn:

- **Executor**: `subagent_candidates(ctx)` returns the full `executor_artifacts`
  list from `task.json`. Immutable files in the list are injected;
  living files (the plan, `milestones.md`) fall into the listing.
- **Reviewer**: `subagent_candidates(ctx)` returns `brief.md` plus the
  charter-specific upstream set (`core-flows.md` for `TECH_PLAN_REVIEWER`;
  `tech-plan.md` and `milestones.md` for `PLAN_REVIEWER`; `tech-plan.md`
  for `MILESTONE_REVIEWER`). The `reviewer_target` is always excluded from
  injection -- the reviewer reads it explicitly via `koan_artifact_read`
  because it is the focus of the review, not a standing handover.
- **Scouts**: excluded -- scouts take no handover artifacts.

See [architecture.md -- Handover injection](./architecture.md#5-need-to-know-prompts)
for the invariants and [subagents.md](./subagents.md) for the spawn path.
