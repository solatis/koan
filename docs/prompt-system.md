# Koan Prompt System

The single source of truth for koan's orchestration prompts. The phase and
workflow modules under `koan/phases/` and `koan/lib/workflows.py` are a
**mechanical translation** of this document. The doc changes first; the code
follows.

This is the prompt analog of [docs/design-system.md](design-system.md): that doc
owns koan's visual language; this one owns its prompt language. Same discipline --
a strict tier hierarchy, single-source fragments, promotion rules, and a
knowledge-direction constraint that keeps the tiers from leaking into each other.

---

## Contents

- [1. The hierarchy](#1-the-hierarchy) -- Workflow -> Phase -> Step -> Fragment, and the prime directive
- [2. Cross-cutting axes](#2-cross-cutting-axes) -- execution context, category, the two review surfaces
- [3. Workflows](#3-workflows) -- the 5 pipelines
- [4. Phases](#4-phases) -- the 11 phases and their binding interface
- [5. Steps](#5-steps) -- the per-turn prompts (factored)
- [6. Fragments](#6-fragments) -- the single home of all verbatim prompt text
- [7. Assembly](#7-assembly) -- how fragments render into a step
- [8. Rationale](#8-rationale) -- the non-obvious WHYs
- [9. Conventions & maintenance](#9-conventions--maintenance)

> **Where the words live.** Verbatim prompt text appears in exactly two places:
> a Step's own unique body ([section 5](#5-steps)) and the Fragments catalog
> ([section 6](#6-fragments)). Everything above them -- Workflows, Phases -- is
> structure that references steps and fragments by identifier. If you are reading
> to understand the system, you never hit a wall of prompt text until you
> deliberately drill into a leaf.

---

## 1. The hierarchy

Four tiers. Each composes the one below it; nothing references upward.

```
Workflow        a pipeline of phases (plan, milestones, initiative, discovery, curation)
  -> Phase      a unit of work: ordered steps + lifecycle + role context
       -> Step  the instruction delivered for ONE turn
            -> Fragment   a reusable, named piece of prompt text
```

| Tier         | Definition                                                                                                  | Count                 | Source of record                                         |
| ------------ | ----------------------------------------------------------------------------------------------------------- | --------------------- | -------------------------------------------------------- |
| **Workflow** | An ordered set of phases + transitions + the per-phase **bindings**. The only home of per-workflow content. | 5                     | `koan/lib/workflows.py`                                  |
| **Phase**    | Ordered steps + lifecycle (next-step, completion gate, loop-back) + a role context. Workflow-agnostic.      | 11                    | `koan/phases/<name>.py`                                  |
| **Step**     | The instruction for one turn, composed from fragments + its own unique body.                                | 24                    | `step_guidance()` per module                             |
| **Fragment** | A named, reusable piece of prompt text. The single source of truth for the words.                           | see [6](#6-fragments) | `koan/phases/`, `koan/prompts/`, `koan/lib/workflows.py` |

### The binding (a phase's "props")

A phase is reused across workflows because the workflow-specific content is
**passed in**, never hardcoded. That parameterization is the `PhaseBinding`:

| Binding field         | What it supplies                                                                  |
| --------------------- | --------------------------------------------------------------------------------- |
| `guidance`            | The `{{PHASE_INSTRUCTIONS}}` injected at the top of step 1 (a guidance fragment). |
| `retrieval_directive` | The query that produces the memory-injection block.                               |
| `next_phase`          | Auto-advance target, or `None` to hand back to the user.                          |
| `description`         | UI label.                                                                         |

The phase also reads runtime values from `PhaseContext` (task description,
returned tool results, prior conversation). Bindings + ctx together are the
complete input surface of a phase -- the thing each step's **contract**
(section 5) makes explicit.

### The prime directive: knowledge flows downward

> A **fragment** knows nothing about which step includes it.
> A **step** must not name another phase or a workflow.
> A **phase** must be workflow-agnostic -- specialization arrives via its binding.
> A **workflow** is the only place per-workflow content lives.

This is the prompt analog of the design system's tier-import constraints (atoms
cannot import molecules). A reference that points upward is a defect, the same
way a hardcoded hex value is a defect in the design system. Known violations are
tracked in [section 9](#9-conventions--maintenance).

---

## 2. Cross-cutting axes

Two tags qualify every phase. They are orthogonal to the tier hierarchy.

### 2.1 Execution context -- where a phase runs

| Context          | Meaning                                                                                                                                      | Phases                                                                   |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| **ORCHESTRATOR** | Runs inline in the single long-lived main agent. Sees the whole conversation -- prior phases, tool results, user answers.                    | intake, core-flows, tech-plan, milestone, plan, execute, curation, frame |
| **SUBAGENT**     | Spawned in a FRESH context by an orchestrator phase. Shares nothing; all input arrives via its system prompt + the files it is told to read. | executor, reviewer, scout                                                |

Subagent phases are **not** workflows and **not** a separate top tier. They are
phases that happen to run in a fresh agent, always nested inside a workflow run:
the orchestrator runs the workflow, and some of its phases delegate to subagent
phases (execute -> executor; an artifact write -> reviewer;
`koan_request_scouts` -> scout).

### 2.2 Category -- what a phase is for

| Category           | Does                                                | Phases                                 |
| ------------------ | --------------------------------------------------- | -------------------------------------- |
| **INTAKE**         | Gather + verify context -> `brief.md`               | intake                                 |
| **PRODUCTION**     | Author a frozen artifact                            | core-flows, tech-plan, milestone, plan |
| **REVIEW**         | Check an artifact / an execution before trusting it | execute (orch), reviewer (subagent)    |
| **IMPLEMENTATION** | Write source code                                   | executor                               |
| **INVESTIGATION**  | Read-only codebase fact-finding                     | scout                                  |
| **CURATION**       | Write project memory                                | curation                               |
| **EXPLORATION**    | Open-ended dialogue, no fixed artifact              | frame                                  |

### 2.3 The two REVIEW surfaces (the easy thing to miss)

"Review" is one function implemented twice, in two contexts that never share
state:

1. **Adversarial pre-exec review -- SUBAGENT.** `koan_artifact_write` on a
   reviewed family (plan / milestones / tech-plan) spawns a fresh `reviewer`
   with a per-family charter. It doubts the artifact and returns findings the
   orchestrator reconciles. -> phase `reviewer` ([4.10](#410-reviewer-subagent)).
2. **Inline post-exec conformance review -- ORCHESTRATOR.** After the executor
   returns, the orchestrator's own `execute` phase runs bash checks, classifies
   conformance, and drives remediation. -> phase `execute` ([4.6](#46-execute)).

Treat them as two prompt families that happen to share the word "review".

---

## 3. Workflows

A workflow owns its phase set, the transitions between them, and the binding it
passes to each phase. All five run in the **orchestrator**. Guidance and
retrieval directives are referenced by fragment id; their text lives in
[section 6](#6-fragments).

Binding notation per phase: `phase (guidance=<frag>, retrieval=<frag>, next=<phase|hand-back>)`.

### 3.1 plan

Lightweight focused-change pipeline. Single executor spawn.

```
intake -> plan -> execute -> curation
```

| Phase    | guidance         | retrieval         | next                 |
| -------- | ---------------- | ----------------- | -------------------- |
| intake   | `g.plan.intake`  | `r.intake.scoped` | plan                 |
| plan     | `g.plan.plan`    | `r.plan`          | hand-back            |
| execute  | `g.plan.execute` | `r.execute`       | hand-back            |
| curation | `g.postmortem`   | (none)            | hand-back (terminal) |

Transitions (UI suggestions): `intake->plan; plan->execute; execute->{curation,plan}`.

### 3.2 milestones

Break work into milestones, then loop plan/execute per milestone.

```
intake -> milestone -> plan -> execute -> (plan | curation | milestone)
```

| Phase     | guidance                 | retrieval         | next                 |
| --------- | ------------------------ | ----------------- | -------------------- |
| intake    | `g.milestones.intake`    | `r.intake.scoped` | milestone            |
| milestone | `g.milestones.milestone` | `r.milestone`     | hand-back            |
| plan      | `g.milestones.plan`      | `r.plan`          | hand-back            |
| execute   | `g.milestones.execute`   | `r.execute`       | hand-back            |
| curation  | `g.postmortem`           | (none)            | hand-back (terminal) |

Transitions: `intake->milestone; milestone->plan; plan->execute; execute->{plan,curation,milestone}`.

### 3.3 initiative

Full-ceremony pipeline with the visualization-first architecture artifacts.

```
intake -> core-flows -> tech-plan -> milestone -> plan -> execute -> (loop | curation)
```

| Phase      | guidance                 | retrieval          | next                 |
| ---------- | ------------------------ | ------------------ | -------------------- |
| intake     | `g.initiative.intake`    | `r.intake.broad`   | core-flows           |
| core-flows | `g.initiative.coreflows` | `r.coreflows`      | hand-back            |
| tech-plan  | `g.initiative.techplan`  | `r.techplan`       | milestone            |
| milestone  | `g.initiative.milestone` | `r.milestone.init` | hand-back            |
| plan       | `g.initiative.plan`      | `r.plan`           | hand-back            |
| execute    | `g.initiative.execute`   | `r.execute`        | hand-back            |
| curation   | `g.postmortem`           | (none)             | hand-back (terminal) |

Transitions: `intake->{core-flows,tech-plan}; core-flows->{tech-plan,core-flows};
tech-plan->milestone; milestone->plan; plan->execute;
execute->{plan,curation,milestone,tech-plan}`.

### 3.4 discovery

Single-phase open-ended exploration. User-driven exit.

```
frame
```

| Phase | guidance            | retrieval | next                 |
| ----- | ------------------- | --------- | -------------------- |
| frame | `g.discovery.frame` | `r.frame` | hand-back (terminal) |

### 3.5 curation (standalone)

Standalone memory maintenance -- the same `curation` phase, entered with the
standalone directive instead of the postmortem one.

```
curation
```

| Phase    | guidance       | retrieval | next                 |
| -------- | -------------- | --------- | -------------------- |
| curation | `g.standalone` | (none)    | hand-back (terminal) |

> The `curation` phase is bound by four workflows. plan/milestones/initiative
> pass `g.postmortem` (source = the run transcript); the standalone curation
> workflow passes `g.standalone` (source = the user's task + existing memory).
> The phase body is directive-agnostic -- a textbook example of binding-as-props.

---

## 4. Phases

Each phase is workflow-agnostic and exposes a **binding interface** (the props it
accepts) plus the **ctx** it reads. Steps are listed by id; their bodies are in
[section 5](#5-steps). Role contexts are fragments, defined in
[section 6](#6-fragments).

Entry shape:

```
### <name>   [CONTEXT] - CATEGORY
Purpose. | Steps: ... | Lifecycle: ... | Role context: <frag> |
Binding interface: ... | Reads ctx: ... | Bound by: <workflows> | Source: <file>
```

### 4.1 intake -- [ORCHESTRATOR] - INTAKE

- **Purpose:** read the task, explore the codebase, interrogate the user, and
  synthesize the frozen `brief.md` every downstream phase trusts.
- **Steps:** `step.intake.1` Gather -> `step.intake.2` Deepen -> `step.intake.3` Summarize.
- **Lifecycle:** linear; step 3 is terminal and auto-advances via `next_phase`.
- **Role context:** `role.intake`.
- **Binding interface:** `guidance` (workflow scope + investigation/question posture), `retrieval_directive`, `next_phase`.
- **Reads ctx:** task_description, project_dir, additional_dirs, workflow_name, memory_injection.
- **Bound by:** plan, milestones, initiative.
- **Source:** `koan/phases/intake.py`.

### 4.2 core-flows -- [ORCHESTRATOR] - PRODUCTION

- **Purpose:** describe externally visible behavior as mermaid sequence diagrams + narratives -> `core-flows.md` (frozen). Yield-skippable.
- **Steps:** `step.core-flows.1` Analyze -> `step.core-flows.2` Write.
- **Lifecycle:** linear; step 2 terminal, hand-back.
- **Role context:** `role.core-flows`.
- **Binding interface:** `guidance`, `retrieval_directive`, `next_phase=None`.
- **Reads ctx:** memory_injection, phase_instructions.
- **Bound by:** initiative.
- **Source:** `koan/phases/core_flows.py`.

### 4.3 tech-plan -- [ORCHESTRATOR] - PRODUCTION

- **Purpose:** describe internal structure (Architectural Approach / Data Model / Component Architecture) -> `tech-plan.md`. The write spawns the `reviewer` subagent (`TECH_PLAN_REVIEWER`).
- **Steps:** `step.tech-plan.1` Analyze -> `step.tech-plan.2` Write (write + reconcile).
- **Lifecycle:** linear; step 2 terminal, auto-advances to milestone via `next_phase`.
- **Role context:** `role.tech-plan`.
- **Binding interface:** `guidance`, `retrieval_directive`, `next_phase=milestone`.
- **Reads ctx:** memory_injection, phase_instructions.
- **Bound by:** initiative.
- **Source:** `koan/phases/tech_plan_spec.py`.

### 4.4 milestone -- [ORCHESTRATOR] - PRODUCTION

- **Purpose:** decompose the initiative into ordered, independently-deliverable milestones -> `milestones.md` (CREATE-only; the discard hook deletes any prior copy on entry). The write spawns the `reviewer` subagent (`MILESTONE_REVIEWER`).
- **Steps:** `step.milestone.1` Analyze -> `step.milestone.2` Write (write + reconcile).
- **Lifecycle:** linear; step 2 terminal, hand-back (advance to plan).
- **Role context:** `role.milestone`.
- **Binding interface:** `guidance`, `retrieval_directive`, `next_phase=None`.
- **Reads ctx:** memory_injection, phase_instructions.
- **Bound by:** milestones, initiative.
- **Source:** `koan/phases/milestone_spec.py`.

### 4.5 plan -- [ORCHESTRATOR] - PRODUCTION

- **Purpose:** write a file-level implementation plan -> the plan artifact (`plan.md` / `plan-milestone-N.md` / `*-remediation-K.md`). The write spawns the `reviewer` subagent (`PLAN_REVIEWER`); naming the plan for execution spawns the `executor`.
- **Steps:** `step.plan.1` Analyze -> `step.plan.2` Write (write + reconcile + name-for-execution).
- **Lifecycle:** linear; step 2 terminal; its body calls `koan_set_phase("execute", plan_file=...)`.
- **Role context:** `role.plan`.
- **Binding interface:** `guidance` (filename + which milestone), `retrieval_directive`, `next_phase=None`.
- **Reads ctx:** memory_injection, phase_instructions.
- **Bound by:** plan, milestones, initiative.
- **Source:** `koan/phases/plan_spec.py`.

### 4.6 execute -- [ORCHESTRATOR] - REVIEW

- **Purpose:** the orchestrator acts as the inline post-exec reviewer. The executor has already run (spawned by the `koan_set_phase("execute", ...)` that entered this phase). Verify conformance, classify, and branch (advance / remediate / escalate). One of two [review surfaces](#23-the-two-review-surfaces-the-easy-thing-to-miss).
- **Steps:** `step.execute.1` Verify -> `step.execute.2` Assess.
- **Lifecycle:** linear; step 2 terminal, hand-back; the branch logic lives in the step body.
- **Role context:** `role.execute`.
- **Binding interface:** `guidance` (outcome paths + whether to UPDATE milestones.md), `retrieval_directive`, `next_phase=None`.
- **Reads ctx:** memory_injection, phase_instructions, the executor deviation report (tool result).
- **Bound by:** plan, milestones, initiative.
- **Source:** `koan/phases/execute.py`.

### 4.7 curation -- [ORCHESTRATOR] - CURATION

- **Purpose:** write project memory. Directive-agnostic body; the source (transcript vs task+memory) is set by the injected directive.
- **Steps:** `step.curation.1` Inventory -> `step.curation.2` Memorize.
- **Lifecycle:** linear; step 2 terminal, hand-back. Both steps are wrapped by the `blk.curation-header` fragment (workflow-shape + goal + tools-this-step).
- **Role context:** `role.curation`.
- **Binding interface:** `guidance` (`g.postmortem` or `g.standalone`), `retrieval_directive=None` (uses `koan_memory_status`).
- **Reads ctx:** phase_instructions (the directive), task_description, the run transcript (postmortem).
- **Bound by:** plan, milestones, initiative (postmortem); curation (standalone).
- **Source:** `koan/phases/curation.py`.

### 4.8 frame -- [ORCHESTRATOR] - EXPLORATION

- **Purpose:** open-ended exploration partner -- design questions, bug hunting, general Q&A. No fixed artifact; never auto-advances.
- **Steps:** `step.frame.1` Explore (single step, repeats across turns).
- **Lifecycle:** single-step; always hand-back; exit via `koan_set_workflow` / `koan_set_phase` / `koan_set_phase("done")`.
- **Role context:** `role.frame`.
- **Binding interface:** `guidance`, `retrieval_directive`, `next_phase=None`.
- **Reads ctx:** task_description, workflow_name, memory_injection, phase_instructions, ongoing dialogue.
- **Bound by:** discovery.
- **Source:** `koan/phases/frame.py`.

### 4.9 executor (subagent) -- [SUBAGENT] - IMPLEMENTATION

- **Purpose:** the only agent that writes source code. Implements a frozen plan.
- **Steps:** `step.executor.1` Comprehend -> `step.executor.2` Plan -> `step.executor.3` Implement.
- **Lifecycle:** linear; final turn returns a structured deviation report (the tool result the orchestrator's `execute` phase reviews).
- **Role context:** none (identity is `sys.executor`).
- **Binding interface:** spawned, not bound. Inputs via task.json: `executor_artifacts`, free-form instructions (-> `phase_instructions`), `run_dir`, optional `retry_context`.
- **Spawned by:** plan / execute (`koan_set_phase("execute", plan_file=...)`).
- **Source:** `koan/phases/executor.py` + `koan/prompts/executor.py`.

### 4.10 reviewer (subagent) -- [SUBAGENT] - REVIEW

- **Purpose:** adversarial pre-exec review of a just-written artifact. Fresh context; read-only; returns findings as final text (koan persists them to the `.review.md` sidecar). One of two [review surfaces](#23-the-two-review-surfaces-the-easy-thing-to-miss).
- **Steps:** `step.reviewer.1` Review -> `step.reviewer.2` Report.
- **Lifecycle:** linear; terminates after step 2.
- **Role context:** none; the per-family **charter** (`charter.plan` / `charter.milestone` / `charter.tech-plan` / `charter.generic`) is injected at the top of step 1. Identity is `sys.reviewer`.
- **Binding interface:** spawned. Inputs via task.json: `reviewer_target`, `reviewer_prompt` (charter selector), `reviewer_predecessor_chain`.
- **Spawned by:** `koan_artifact_write` on a reviewed family (plan / milestones / tech-plan).
- **Source:** `koan/phases/reviewer.py` + `koan/prompts/reviewer.py`.

### 4.11 scout (subagent) -- [SUBAGENT] - INVESTIGATION

- **Purpose:** answer one narrow codebase question with grounded, read-only facts. Returns a compressed report.
- **Steps:** `step.scout.1` Investigate -> `step.scout.2` Verify -> `step.scout.3` Report.
- **Lifecycle:** linear; terminates after step 3.
- **Role context:** none (identity is `sys.scout`).
- **Binding interface:** spawned. Inputs via task.json: `scout_question`, `scout_investigator_role`, `project_dir`/`additional_dirs` (scope fence).
- **Spawned by:** `koan_request_scouts` (allowed in intake, core-flows, tech-plan, plan, milestone, curation, frame).
- **Source:** `koan/phases/scout.py` + `koan/prompts/scout.py`.

---

## 5. Steps

A step is the instruction delivered for one turn. Each entry below has a
**contract** (its input/output surface) and a **body** in factored form: unique
prose inline, shared blocks as `{{> fragment(param="...")}}` references whose text
lives in [section 6](#6-fragments).

**Reading the body notation.**

- `{{> name(...)}}` -- include the named fragment ([section 6](#6-fragments)),
  with the given parameters. Distinct from `{{VAR}}`, which is a value injected
  at runtime (task description, retrieved memory, etc.).
- Every step-1 body opens with `{{> blk.step1-head(...)}}` -- the standard
  injected preamble (optional workflow line, the guidance heading + the
  `{{PHASE_INSTRUCTIONS}}` injection, the memory block). The role context and the
  closing invoke footer are added by the [assembly](#7-assembly) layer, not the
  body, so they are not repeated in each entry.

**Contract fields:** `[inferred]` = derived from the code (correct if wrong);
`TODO(you)` = intent for the maintainer to author.

Factoring follows the promotion rule ([6](#6-fragments)): a block is a fragment
iff 2+ steps use it. Per-step variance against a fragment's canonical text is
noted in the fragment's entry as a refactor target.

### intake

#### step.intake.1 -- Gather

- **Contract**
  - Context in [inferred]: `role.intake`; `guidance` (workflow scope/posture); `inj.memory`; `{{TASK_DESCRIPTION}}`; project roots. First turn -- no prior conversation.
  - Artifacts required [inferred]: none (run just started).
  - Artifacts optional [inferred]: README / AGENTS.md / CLAUDE.md; files named in the task (<= 5 orientation reads).
  - Produces [inferred]: optional `koan_request_scouts`; `koan_reflect`/`koan_search`; an investigation plan.
  - Purpose / Success / Failure: TODO(you).
- **Body**

```text
{{> blk.step1-head(workflow_line=yes, heading="## Workflow Context")}}

Read the task description, orient yourself in the codebase, and plan your investigation.

{{> blk.no-writes(what="brief.md or any other artifact")}}

## 1. Task description

{{> env.task}}

As you read the task, track:
- **Topic**: What is being built or changed?
- **File references**: Every file, directory, or module mentioned.
- **Decisions already made**: Only those explicitly stated and agreed upon.
- **Constraints**: Technical, timeline, compatibility requirements.
- **Gaps**: Questions raised but unanswered. Things unclear or unstated that would affect scope.
- **Conventions mentioned**: coding standards, test approaches, doc standards, patterns to follow.

Be faithful to what was said. Do not invent context or infer unstated decisions.

## 2. Quick orientation -- open obvious files

{{PROJECT_ROOTS}}

Open up to **5 files** that any investigation would start from: `ls` the root;
open README.md / AGENTS.md / CLAUDE.md if present; open any file the task
referenced (skim first 50-100 lines); one `find`/`ls` to locate a named module.
Budget: 5 reads. This is orientation, not investigation -- just enough to write
scout prompts that reference real names and paths.

## 3. Consult project memory

{{> blk.consult-memory(
     topic   = "the area the task touches",
     example = "what does the project know about the X subsystem?",
     closing = "Only after this should you plan scouts." )}}

## 4. Plan your investigation

Direct reading (focused, reachable files) vs scouts (`koan_request_scouts`:
unfamiliar subsystems, broad tracing, parallel coverage). Use both. The workflow
context above tells you which posture to default to. Each scout needs:
`id` (kebab-case), `role` (investigator focus), `prompt` (a 3-8 sentence brief
citing real paths/function names). Dispatch all scouts in one call.
```

#### step.intake.2 -- Deepen

- **Contract**
  - Context in [inferred]: the step-1 conversation + returned scout reports; `role.intake` persists; user answers as they arrive.
  - Artifacts required [inferred]: scout reports from the step-1 dispatch (if any).
  - Artifacts optional [inferred]: codebase files confirming findings; `koan_search`.
  - Produces [inferred]: `koan_ask_question` rounds; an in-conversation known/unknown map.
  - Purpose / Success / Failure: TODO(you).
- **Body** (no shared fragments -- unique to intake)

```text
Deepen your understanding through iterative dialogue with the user. Scout results
are a starting point, not the finish line.

{{> blk.no-writes(what="brief.md")}}

## 1. Process scout results
For each report: does it answer your questions? reveal anything unexpected?
conflict with the task? For key findings that affect scope, open the actual files.

## 2. Map what you know and what you don't
Per area: **Known** / **Unknown** / **Source**. Cover every area incl. conventions.
Use `koan_search` to check for prior lessons. Mark each unknown **ASK** (affects
scope/approach/sequencing) or **SAFE** (implementation detail).

## 3. The deepening loop
a) **Ask** -- `koan_ask_question` for every ASK. Prefer multiple-choice when bounded;
   plain-text labels (no (a)/(b), no "Other"); rich `context` field; crisp `question`;
   ground in findings ("Scout found X -- same pattern?").
b) **Deepen** -- each answer is a thread: read referenced files, revise your picture,
   surface assumptions, raise new questions.
c) **Follow up** -- new unknowns -> `koan_ask_question` again (rounds per workflow context).
d) **Done when** -- every area verified; you can brief a planner without hedging; no
   "I think I know what they mean" left unresolved.
```

#### step.intake.3 -- Summarize (terminal)

- **Contract**
  - Context in [inferred]: full intake conversation; `role.intake`.
  - Artifacts required [inferred]: none on disk (synthesises from conversation).
  - Artifacts optional [inferred]: re-reads to pin exact paths.
  - Produces [inferred]: `brief.md` via `koan_artifact_write` (7 sections, frozen); then `{{> foot.advance(next_phase)}}`.
  - Purpose / Success / Failure: TODO(you).
- **Body** (unique; the write-call skeleton is shared in spirit but the section template is intake-specific)

```text
Synthesize the seven-section initiative brief and write it to `brief.md`.

Sections: 1 **Initiative** (one paragraph) - 2 **Scope** (in / out; out matters
more) - 3 **Affected subsystems** (real paths, verified) - 4 **Decisions** (choice
+ rejected alternatives) - 5 **Constraints** - 6 **Assumptions** (falsifiable) -
7 **Open questions**. Empty section -> `(none)`; never omit a section.

Write via `koan_artifact_write(filename="brief.md", content="""# <title> ... """)`.

brief.md is FROZEN at exit -- authoritative for every downstream phase, never
rewritten. A wrong assumption surfaces later in a milestone Outcome or a chat
note, not by editing brief.md.
```

### core-flows

#### step.core-flows.1 -- Analyze

- **Contract**
  - Context in [inferred]: `role.core-flows`; `guidance`; `inj.memory`; intake dialogue.
  - Artifacts required [inferred]: `brief.md`.
  - Artifacts optional [inferred]: memory.
  - Produces [inferred]: a flow list with per-flow diagram-vs-prose decision. No writes.
  - Purpose / Success / Failure: TODO(you).
- **Body**

```text
{{> blk.step1-head(heading="## Workflow guidance")}}

{{> blk.read-brief(
     when = "first via koan_artifact_read",
     why  = "The flows you describe must correspond to the operational behavior the initiative implies." )}}

{{> blk.consult-memory(
     topic   = "the system's operational behavior, user-visible flows, and integration points",
     example = "what do we know about how X works end to end?" )}}

{{> blk.no-writes(what="any files")}}

## Identify flows
Enumerate the operational flows the initiative implies. Per flow: Name - Actors -
Trigger - Sequenced steps - Exit conditions - Diagram decision (a `sequenceDiagram`,
or prose only when 2 actors AND < 4 messages AND no branching).

End your turn with: the flow list; per-flow diagram-vs-prose decision + rationale;
any operational-behavior ambiguities to resolve.
```

#### step.core-flows.2 -- Write (terminal)

- **Contract**
  - Context in [inferred]: the step-1 flow analysis; `role.core-flows`.
  - Artifacts required [inferred]: `brief.md` (already read).
  - Produces [inferred]: `core-flows.md` via `koan_artifact_write` (frozen); `{{> foot.yield}}`.
  - Purpose / Success / Failure: TODO(you).
- **Body** (unique -- the SEQ-slot rules and write template are core-flows-specific)

```text
Compose `core-flows.md` and submit via `koan_artifact_write`. One section per flow
(`## Flow N: <title>`): a mermaid `sequenceDiagram` OR prose only (no marker, no
placeholder) when 2 actors AND < 4 messages AND no branching; plus a step
narrative (trigger, sequenced steps, exit conditions).

Constraints (repeated at point of use): no file paths / component names /
implementation detail; SEQ only (no CON/CMP/STT); grounding rule (no actor absent
from brief.md + dialogue); FROZEN at exit.
```

### tech-plan

#### step.tech-plan.1 -- Analyze

- **Contract**
  - Context in [inferred]: `role.tech-plan`; `guidance`; `inj.memory`.
  - Artifacts required [inferred]: `brief.md`.
  - Artifacts optional [inferred]: `core-flows.md` (if present); scouts; memory.
  - Produces [inferred]: a 3-section outline + per-slot diagram decisions. No writes.
  - Purpose / Success / Failure: TODO(you).
- **Body**

```text
{{> blk.step1-head(heading="## Workflow guidance")}}

{{> blk.read-brief(
     when = "and core-flows.md (if present) via koan_artifact_read, before anything else",
     why  = "core-flows.md is authoritative for the actors and flows that constrain the architecture." )}}

{{> blk.consult-memory(
     topic   = "architectural decisions and constraints relevant to the new system's structure",
     example = "what architectural decisions constrain changes to X?" )}}

{{> blk.no-writes(what="any files")}}

## Investigate codebase
Dispatch scouts (`koan_request_scouts`) for integration points: existing module
structure, data-model schemas, integration seams the architecture will touch.

## Identify the three sections' content
Per slot decide diagram vs prose-only (suppression thresholds: CON single/2-container;
CMP < 4 components; SEQ 2 actors & < 4 msgs & no branch; STT < 3 states or no guards;
Data Model = fenced code, not ER). Check grounding: every node traces to a named
concept in the inputs.

End your turn with: a 3-section outline; per-slot diagram-vs-prose decisions + rationale;
architectural questions to resolve before writing.
```

#### step.tech-plan.2 -- Write (terminal, advance)

- **Contract**
  - Context in [inferred]: the step-1 outline; `role.tech-plan`.
  - Artifacts required [inferred]: `brief.md`.
  - Produces [inferred]: `tech-plan.md` via `koan_artifact_write` -> spawns `TECH_PLAN_REVIEWER`; reconcile; then `koan_set_phase("milestone")`.
  - Purpose / Success / Failure: TODO(you).
- **Body**

```text
Compose `tech-plan.md` and submit via `koan_artifact_write`. Three required sections,
each with chosen path AND rejected alternatives + rationale:
- **Architectural Approach** -- CON diagram (flowchart container view), suppress per threshold.
- **Data Model** -- fenced code blocks (NOT ER diagrams).
- **Component Architecture** -- CMP (classDiagram/flowchart per container); SEQ for
  cross-component flows; STT for entity lifecycles when warranted.

Constraints (repeated): grounding rule; level-separation (no cross-level mixing);
below-threshold slots = prose only, no marker.

{{> blk.reviewer-reconcile(
     artifact = "tech-plan.md",
     reviewer = "TECH_PLAN_REVIEWER",
     sidecar  = "tech-plan.review.md" )}}

After reconciling, advance to the next phase.
```

### milestone

#### step.milestone.1 -- Analyze

- **Contract**
  - Context in [inferred]: `role.milestone`; `guidance`; `inj.memory`.
  - Artifacts required [inferred]: `brief.md`; (initiative) `tech-plan.md`.
  - Artifacts optional [inferred]: `core-flows.md`; module tree; import graph; memory.
  - Produces [inferred]: a proposed 3-7 milestone list with scope + sizing. No writes (prior milestones.md discarded on entry).
  - Purpose / Success / Failure: TODO(you).
- **Body**

```text
{{> blk.step1-head(heading="## Workflow guidance")}}

{{> blk.read-brief(
     when = "before proposing milestones",
     why  = "It contains the frozen scope, decisions, constraints, and affected subsystems -- authoritative." )}}

{{> blk.no-writes(what="milestones.md")}}

## Read the module structure
Read the directory tree + top-level packages (find/ls/tree), not individual files
-- the prior for where milestones should cut. Identify the affected subgraph from
intake findings; read the import graph among touched modules.

{{> blk.consult-memory(
     topic   = "architectural constraints relevant to milestone scope and ordering",
     example = "past decomposition patterns or subsystem boundary decisions" )}}

## Propose milestones
3-7 milestones. Per milestone: name the files/modules it owns (greenfield aside,
ungroundable scope = not grounded); verify no two claim the same file; check sizing
(5-30 files, 10-30 plan steps, <= 6-sentence sketch); order by dependency.

End your turn with the proposed list (sketches + file/module scope).
```

#### step.milestone.2 -- Write (terminal)

- **Contract**
  - Context in [inferred]: the step-1 list; `role.milestone`.
  - Produces [inferred]: `milestones.md` via `koan_artifact_write` -> spawns `MILESTONE_REVIEWER`; reconcile; advance to plan.
  - Purpose / Success / Failure: TODO(you).
- **Body**

```text
Write `milestones.md` via `koan_artifact_write`. Give the **first** milestone
`[in-progress]`, the rest `[pending]`; each a 3-6 sentence sketch; order by
dependency. (Always CREATE -- the discard hook removed any prior copy on entry.)

{{> blk.reviewer-reconcile(
     artifact = "milestones.md",
     reviewer = "MILESTONE_REVIEWER",
     sidecar  = "milestones.review.md" )}}

Then advance to plan.
```

### plan

#### step.plan.1 -- Analyze

- **Contract**
  - Context in [inferred]: `role.plan`; `guidance` (filename + current milestone); `inj.memory`.
  - Artifacts required [inferred]: `brief.md`; (milestones/initiative) `milestones.md`; (initiative) `tech-plan.md`.
  - Artifacts optional [inferred]: `core-flows.md`; codebase files; memory.
  - Produces [inferred]: an analysis summary (approach, files, decisions, risks, docstring needs). No writes.
  - Purpose / Success / Failure: TODO(you).
- **Body**

```text
{{> blk.step1-head(heading="## Workflow guidance")}}

{{> blk.read-brief(
     when = "before consulting memory or reading codebase files",
     why  = "The plan you write must respect every decision and constraint listed there." )}}

{{> blk.consult-memory(
     topic   = "the subsystems you will plan changes for",
     example = "what conventions govern changes to the X subsystem?",
     closing = "Only after this should you read codebase files." )}}

{{> blk.no-writes(what="any files")}}

## What to read
Trust intake's findings -- a starting point, not something to re-investigate. Read
the files the plan will reference: function signatures + type names, integration
points, ordering constraints.

## What to analyze
Identify: key architectural decisions; integration points; risks; safe step order;
documentation needs (every added/modified function needs a docstring directive at
its step). End with an analysis summary (approach; files; decisions + rationale;
ambiguities/risks).
```

#### step.plan.2 -- Write (terminal; names plan for execution)

- **Contract**
  - Context in [inferred]: the step-1 analysis; `role.plan`.
  - Artifacts required [inferred]: the plan filename (from guidance/step 1).
  - Produces [inferred]: the plan artifact via `koan_artifact_write` -> spawns `PLAN_REVIEWER`; reconcile; `koan_set_phase("execute", plan_file=...)` (freezes plan, spawns executor, returns deviation report).
  - Purpose / Success / Failure: TODO(you).
- **Body**

```text
Compose the full plan and submit via `koan_artifact_write` (filename from workflow
guidance; default plan.md). Required sections: **Approach summary** (2-4 sentences);
**Key decisions** (choice + why + rejected alternative); **Implementation steps**
(per step: File, Location, Change -- specific; **Documentation** directive for any
added/modified function); **Constraints** (from brief.md); **Verification**.
Order steps so dependencies precede dependents. Do NOT use Write/Edit.

{{> blk.reviewer-reconcile(
     artifact = "the plan",
     reviewer = "PLAN_REVIEWER",
     sidecar  = "<plan-stem>.review.md" )}}

## Name the plan for execution
After reconciling, `koan_set_phase("execute", plan_file="<the plan you wrote>")` --
freezes the plan byte-identical, spawns the executor (blocking), returns the
deviation report.
```

### execute

#### step.execute.1 -- Verify

- **Contract**
  - Context in [inferred]: `role.execute`; `guidance` (outcome paths); `inj.memory`; the executor deviation report (tool result).
  - Artifacts required [inferred]: `brief.md`; the executed plan; (milestones/initiative) `milestones.md`.
  - Artifacts optional [inferred]: the `.review.md` sidecar.
  - Produces [inferred]: bash verification runs + a verification summary. No writes yet.
  - Purpose / Success / Failure: TODO(you).
- **Body**

```text
{{> blk.step1-head(heading="## Workflow guidance")}}

{{> blk.read-brief(
     when = "and the executed plan artifact (the plan_file you passed)",
     why  = "Assess whether the implementation respects every stated decision and constraint, not just the plan." )}}

## Read milestone state (milestones/initiative only)
If the workflow guidance says to update milestones.md, read it now -- you need its
current state for the step-2 UPDATE.

## Run verification commands
Build/compile; run tests (use `grep -q PATTERN file && echo "FAIL"` for negative
checks); type-checks. Compare against the executor's deviation report. Your bash
checks are authoritative -- a clean executor exit does NOT override failing
builds/tests.

{{> blk.no-writes(what="an assessment yet")}}

End your turn with a verification summary: commands run + results; planned goals
met vs incomplete.
```

#### step.execute.2 -- Assess (terminal; branches)

- **Contract**
  - Context in [inferred]: the step-1 verification; the deviation report; `guidance` (outcome paths).
  - Artifacts required [inferred]: the plan's `.review.md` sidecar; (CLEAN, milestones/initiative) `milestones.md`.
  - Produces [inferred]: conformance classification; `## Execution review (post-exec)` appended to the sidecar; then a branch (advance / remediate / escalate).
  - Purpose / Success / Failure: TODO(you).
- **Body** (unique -- the remediation state machine is execute-specific)

```text
Classify conformance (Conforming/clean vs Non-conforming) from step-1 results --
your verification is authoritative. Append a `## Execution review (post-exec)`
section to the plan's `.review.md` sidecar (freeze-exempt) via koan_artifact_edit:
outcome, commands+results, deviations, summary.

Branch:
- **CLEAN** -- if guidance says so, apply the milestones.md UPDATE (mark `[done]`;
  append a four-subsection `### Outcome` -- Integration points / Patterns /
  Constraints discovered / Deviations; advance next `[pending]` to `[in-progress]`;
  preserve prior Outcomes). Then end your turn per guidance.
- **NON-CONFORMING, base plan** -- `koan_set_phase("plan")`, write
  `<plan-base>-remediation-1.md` folding the failure signal (deviation report +
  your verification + unaddressed findings) into the artifact text, re-execute.
- **NON-CONFORMING, already a remediation** -- the one-attempt cap is reached;
  escalate via `koan_ask_question` (accept-as-is / abort / direct-further-attempts).
```

### curation

#### step.curation.1 -- Inventory

- **Contract**
  - Context in [inferred]: `role.curation`; `blk.curation-header`; the directive (`g.postmortem`/`g.standalone`); `{{TASK_DESCRIPTION}}`; (postmortem) the run transcript.
  - Artifacts required [inferred]: `koan_memory_status` output.
  - Artifacts optional [inferred]: `brief.md`; direct `.koan/memory/` reads; coding-agent memory; (standalone) scouts/docs/interview.
  - Produces [inferred]: a numbered candidate list (type + classification). No writes.
  - Purpose / Success / Failure: TODO(you).
- **Body**

```text
{{> blk.curation-header(step=1)}}

If `brief.md` exists, read it (postmortem context; standalone usually has none).

## Step 1: Inventory
Produce a numbered candidate list; write nothing.

<directive>{{PHASE_INSTRUCTIONS}}</directive>
<task>{{TASK_DESCRIPTION | "(no user task -- see your directive)"}}</task>

Procedure: 1) `koan_memory_status` FIRST (summary + listing). 2) Read your directive
(where the source lives + authorized moves). 3) Read <task> if non-empty per directive.
4) Gather source per posture (postmortem -> transcript; review -> suspect entries +
scouts; document -> the doc + scouts; bootstrap -> scouts + README/AGENTS/CLAUDE +
interview). 5) Consult the coding agent's own memory (read-only input, NOT koan
memory). 6) Build the list: per candidate note type (4-question tree in role context),
title, classification (ADD/UPDATE/NOOP/DEPRECATE/COMMENT), entry_id (UPDATE/DEPRECATE);
read suspect entries directly before classifying.

Do not end until you have >= 1 ADD/UPDATE/DEPRECATE candidate -- unless the source
genuinely has no novel knowledge, then say so explicitly and end.
```

#### step.curation.2 -- Memorize (terminal)

- **Contract**
  - Context in [inferred]: the candidate list; `role.curation` writing rules; `blk.curation-header`.
  - Artifacts required [inferred]: existing `.koan/memory` entries for UPDATE/DEPRECATE.
  - Produces [inferred]: `koan_memorize`/`koan_forget` calls after the per-batch draft/self-critique/revise loop; a final `koan_memory_status`; a counts report.
  - Purpose / Success / Failure: TODO(you).
- **Body** (the bulk -- writing discipline, examples, the 9-item checklist -- is a fragment, because the role context references the same rules)

```text
{{> blk.curation-header(step=2)}}

## Step 2: Memorize
Turn the candidate list into `koan_memorize`/`koan_forget` calls, written directly
after the per-draft self-critique passes.

{{> blk.curation-writing-rules}}

## The per-batch loop (in order, committed visible output per substep)
A **Draft** all non-NOOP candidates (modeled on the GOOD examples) -> B **Self-critique**
(the 9-item checklist, per draft, in the exact format) -> C **Revise** (rewrite any
FAIL completely; loop to all-PASS) -> D **Write** (ADD/UPDATE -> koan_memorize;
DEPRECATE -> koan_forget) -> E **Cross off** and loop with the next batch.

## Anticipatory check (before wrap-up)
Did you call koan_memorize for ADD/UPDATE and koan_forget for DEPRECATE on a
non-empty list? If not, loop back. (Empty list = zero writes is correct.)

## Wrap-up
`koan_memory_status` once; report counts `{added, updated, deprecated, noop}` + a
one-line note on anything deferred.
```

> **Refactor flag (carried from the inventory):** the curation checklist is called
> "9-item" but substep C says "re-run the 8-item checklist". Fixed in one place once
> `blk.curation-writing-rules` is the single source.

### frame

#### step.frame.1 -- Explore (single step; always hand-back)

- **Contract**
  - Context in [inferred]: `role.frame`; `guidance`; `inj.memory`; `{{TASK_DESCRIPTION}}`; ongoing dialogue.
  - Artifacts required [inferred]: none.
  - Artifacts optional [inferred]: memory; codebase reads / scouts / bash.
  - Produces [inferred]: dialogue turns; on exit `koan_set_workflow` / `koan_set_phase` / `koan_set_phase("done")`. No artifact unless the user names one.
  - Purpose / Success / Failure: TODO(you).
- **Body**

```text
{{> blk.step1-head(workflow_line=yes, heading="## Workflow guidance")}}

## Task description
{{> env.task}}

## Your posture
General-purpose exploration partner: feature design, bug hunting, or any question.
Refuse nothing -- answer, investigate, troubleshoot, conclude, recommend. One
guardrail: name large, hard-to-reverse architectural directions as a decision for
the user, don't commit silently.

## Finding prior context and investigating
Surface prior context first: `koan_reflect` (broad), `koan_search` (specific). When
the question calls for it (esp. bug hunting) investigate directly: Read/Grep/Glob;
`koan_request_scouts` for broad tracing; `bash` to reproduce.

## Ask freely
`koan_ask_question` when intent is unclear -- clarifying early is welcome.

## No artifact without negotiation
Do NOT `koan_artifact_write` until the user has chosen and named an artifact shape.

## Always hand back
End every turn with a plain-text message and no tool call. Frame never auto-advances.

## Exit
When the user is ready, present three options: promote via `koan_set_workflow`;
`koan_set_phase` within the workflow; or `koan_set_phase("done")`.
```

### executor (subagent)

#### step.executor.1 -- Comprehend

- **Contract**
  - Context in [inferred]: `sys.executor` (no role context); `{{EXECUTOR_ARTIFACTS}}`; orchestrator `{{PHASE_INSTRUCTIONS}}`; `{{RUN_DIR}}`; (retry) `{{RETRY_CONTEXT}}`.
  - Artifacts required [inferred]: the listed plan artifact(s).
  - Artifacts optional [inferred]: codebase files; `.koan/memory` (read-only).
  - Produces [inferred]: a comprehension summary. No code.
  - Purpose / Success / Failure: TODO(you).
- **Body** (unique)

```text
Read and understand the scope before writing any code.

## Artifacts to read
{{EXECUTOR_ARTIFACTS}}  (each `{{RUN_DIR}}/<artifact>`; else "read all relevant files")

## Instructions from orchestrator
{{PHASE_INSTRUCTIONS | "(no additional instructions)"}}

## What to understand
Read every artifact; for each file/module it references, open it and model: what
changes are needed, which files, what order, risks/edge cases. Do NOT write code.
End with a comprehension summary (changes + order; files affected; ambiguities --
note, don't block).

{{? RETRY_CONTEXT}}
## Retry context -- read this first
A previous execution failed. Failure summary: {{RETRY_CONTEXT}}. Keep it in mind.
{{/RETRY_CONTEXT}}
```

#### step.executor.2 -- Plan

- **Contract**
  - Context in [inferred]: the step-1 comprehension; `sys.executor`.
  - Produces [inferred]: an implementation-approach explanation. No file, no code.
  - Purpose / Success / Failure: TODO(you).
- **Body** (unique)

```text
Explain your implementation approach before coding: what you will change and in what
order; risks/edge cases; how you will verify. Do NOT write a plan file -- this is
reasoning made visible for the audit trail. End your turn to advance.
```

#### step.executor.3 -- Implement

- **Contract**
  - Context in [inferred]: the step-2 approach; the plan; `sys.executor`.
  - Artifacts required [inferred]: target codebase files.
  - Produces [inferred]: source-code edits; rationale comments; build/test runs; a structured deviation report (final turn -> tool result for execute).
  - Purpose / Success / Failure: TODO(you).
- **Body** (unique)

```text
Implement per your step-2 plan. For each change: read the target file, make the
change, move on. **Rationale comments** (1-3 lines, "why" not "what") at each choice.
Resolve trivial issues (wrong path/typo/missing import) independently; `koan_ask_question`
only for genuine ambiguity / non-trivial plan-vs-codebase conflict / blocking
prerequisite. Verify (build/tests). End with a **deviation report**: Implemented as
planned / Deviations / Unanticipated decisions / Incomplete (state "No deviations" if so).
```

### reviewer (subagent)

#### step.reviewer.1 -- Review

- **Contract**
  - Context in [inferred]: `sys.reviewer` (fresh context); the charter (`charter.*`, by `{{reviewer_prompt}}`); `{{reviewer_target}}`; `{{reviewer_predecessor_chain}}` (remediation).
  - Artifacts required [inferred]: the target artifact; `brief.md`; charter-specific upstream (tech-plan/milestones/core-flows, "if present").
  - Artifacts optional [inferred]: predecessor chain; codebase (Read/Grep/Glob/bash); memory.
  - Produces [inferred]: a problem list + verification notes. No writes.
  - Purpose / Success / Failure: TODO(you).
- **Body**

```text
## Reviewer charter
{{> charter[reviewer_prompt]}}   (charter.plan | charter.milestone | charter.tech-plan | charter.generic)

## Target artifact
Read `{{reviewer_target}}` via koan_artifact_read.

## Context artifacts
Read `brief.md` (frozen scope to evaluate against). Then, by charter:
TECH_PLAN_REVIEWER -> core-flows.md (if present); PLAN_REVIEWER -> tech-plan.md +
milestones.md (if present); MILESTONE_REVIEWER -> tech-plan.md (if present).

{{? reviewer_predecessor_chain}}
## Predecessor chain (remediation context)
A remediation review. Read each prior failed attempt in order: {{reviewer_predecessor_chain}}.
{{/reviewer_predecessor_chain}}

## Verify against codebase + memory
Read/Grep/Glob/bash to verify non-obvious claims directly -- do not accept at face
value. `koan_reflect` (correct approach for the area); `koan_search` (relevant past
decisions/lessons). Read files in parallel. Do NOT write. End with: problems found
so far; what you verified and how; remaining verification.
```

#### step.reviewer.2 -- Report

- **Contract**
  - Context in [inferred]: the step-1 problems; the charter.
  - Produces [inferred]: severity-classified findings as final text -> persisted to `<stem>.review.md` by koan. No file writes by the reviewer.
  - Purpose / Success / Failure: TODO(you).
- **Body** (unique)

```text
Output findings as your final text response. By severity: **Critical** (executor
fails / wrong results) / **Major** (significant gap requiring revision) / **Minor**
(author can resolve). Per finding: state it precisely; cite the section/claim; note
approach-invalidating vs targeted fix. End with a one-line tally ("2 Critical, 1
Major, 3 Minor") or "No significant findings". Do NOT write to any file.
```

### scout (subagent)

#### step.scout.1 -- Investigate

- **Contract**
  - Context in [inferred]: `sys.scout` (no role context); `{{SCOUT_QUESTION}}`; `{{SCOUT_INVESTIGATOR_ROLE}}`; project roots (scope fence).
  - Artifacts required [inferred]: none (searches the codebase).
  - Produces [inferred]: candidate files + read excerpts with file:line. No writes.
  - Purpose / Success / Failure: TODO(you).
- **Body**

```text
Find and read the relevant code to answer the question.

## Your assignment
**Question:** {{SCOUT_QUESTION}}
**Your investigator role:** {{SCOUT_INVESTIGATOR_ROLE}}

{{> blk.scope-fence}}

## Actions
1) Parse the question. 2) Cast a wide net (grep/find/glob, multiple at once).
3) Read the most promising files immediately (3-5 at a time). 4) Follow imports/
call chains in batches. 5) Note file:line + verbatim excerpt per finding.
6) Thorough but fast -- drop irrelevant files immediately.
```

#### step.scout.2 -- Verify

- **Contract**
  - Context in [inferred]: the step-1 findings; `sys.scout`.
  - Produces [inferred]: corrected/verified findings + a gap list. No writes.
  - Purpose / Success / Failure: TODO(you).
- **Body** (unique)

```text
Spot-check before reporting: pick the 2-3 most critical claims; verify each with a
targeted call (grep a name, read a line range, ls a path); correct discrepancies,
drop dead references; organize into a clear answer; identify gaps; note what is
explicitly NOT present.
```

#### step.scout.3 -- Report

- **Contract**
  - Context in [inferred]: the step-2 verified findings; `sys.scout`.
  - Produces [inferred]: a compressed, signal-dense report as final text -> returned to the dispatching phase. No writes.
  - Purpose / Success / Failure: TODO(you).
- **Body** (unique)

```text
Output findings as your final response -- compressed, signal-dense, no padding, no
file. **Question** (one line). **Findings**: one bullet per finding, file:line
required; signatures as `file:line func Name(args) returns`; structs as
`Type{F1, F2}`; enums as `E: A|B|C`; call chains as `a.go:10 -> b.go:25`; group
under sub-headings. **Gaps**: bullets, or `(none)`.
```

---

## 6. Fragments

The single source of truth for prompt text. A block is a fragment iff it is
reused by 2+ steps/phases, OR it is a named slot-filler the assembly layer
composes (footers, the memory block, role contexts, guidance injections, system
prompts, charters). Each fragment is defined **once** here; every reference
elsewhere is `{{> id(...)}}`.

Naming: `inj.*` injected blocks - `foot.*` invoke footers - `env.*` envelopes -
`blk.*` shared body blocks - `role.*` phase role contexts - `sys.*` system
prompts - `charter.*` reviewer charters - `g.*` guidance injections -
`r.*` retrieval directives.

> **Migration status.** 6.1 and 6.2 (the structural fragments and the
> newly-promoted shared blocks) are authored here as the canonical source.
> 6.3-6.6 (role contexts, system prompts, charters, guidance) are large verbatim
> blocks that currently also exist in `prompt-inventory.md`; their entries below
> carry id / params / used-by / source, and their canonical bodies are migrated
> from the inventory in the consolidation pass (after which `prompt-inventory.md`
> is retired, leaving this as the one doc).

### 6.1 Structural fragments (assembly layer)

**`inj.memory`** -- the `## Relevant memory` block. Rendered at the step-0->1
handshake only when the phase binding has a `retrieval_directive` AND retrieval
returns results; empty otherwise. Source: `koan/memory/retrieval/rag.py`
(`render_injection_block`). Used by: every step-1 with a retrieval directive.

```text
## Relevant memory

The following memory entries were retrieved based on the retrieval
directive for this phase and the current workflow context. Treat
them as prior knowledge -- decisions, procedures, lessons, and
context from past workflow runs that are likely to matter here.

### {{ENTRY_TITLE}}
*type: {{ENTRY_TYPE}} | modified: {{ENTRY_MODIFIED}}*

{{ENTRY_BODY}}

(... one ### block per retrieved entry, up to k=5 ...)
```

**`foot.default`** -- mid-step footer (`DEFAULT_INVOKE`). Source:
`koan/phases/format_step.py`. Used by: every non-terminal step.

```text
WHEN DONE: end your turn once this step's work is complete -- a turn that ends with no further tool call advances you to the next step automatically. Do not end your turn until the step's work is done.
```

**`foot.advance(next_phase)`** -- terminal footer when the phase auto-advances.
Source: `format_step.py` (`terminal_invoke`). Used by: step.intake.3,
step.tech-plan.2.

```text
WHEN DONE:
1. Summarize what was accomplished in this phase as your final message.
2. Default: call `koan_set_phase("{{next_phase}}")` to advance to the next phase.
3. If exceptional circumstances warrant user direction, end your turn
   with that summary and your recommended next steps as a plain-text
   message (do NOT call a tool) -- ending your turn hands control back
   to the user, who will reply with how to proceed.

The directive above is the terminal action for this phase.
```

**`foot.yield(suggested?)`** -- terminal footer when the phase hands back to the
user. Source: `format_step.py` (`terminal_invoke`). Used by: every other terminal
step (core-flows.2, milestone.2, plan.2, execute.2, curation.2, frame.1).

```text
WHEN DONE:
1. Summarize what was accomplished in this phase as your final message,
   and list the reasonable next-phase options{{ (e.g. {{suggested}})}}, plus
   the option to end the workflow ("done").
2. End your turn with that summary as a plain-text message (do NOT call a
   tool). A turn with no tool call is the hand-back: the loop parks and
   waits for the user's reply.
3. Once the user confirms a direction, call `koan_set_phase(<phase>)` (or
   `koan_set_phase("done")` to end the workflow).

Ending your turn is the terminal action for this phase.
```

**`env.task`** -- task-description envelope. Source: intake.py / frame.py. Used
by: step.intake.1, step.frame.1.

```text
<task_description>
{{TASK_DESCRIPTION}}
</task_description>
(or "(No task description provided.)" when empty)
```

**`blk.step1-head(workflow_line?, heading)`** -- the standard step-1 preamble the
body opens with. `heading` is `## Workflow Context` for intake, `## Workflow
guidance` for every other phase. Used by: every step-1.

```text
{{? workflow_line}}Active workflow: **{{WORKFLOW_NAME}}**{{/workflow_line}}

{{heading}}

{{PHASE_INSTRUCTIONS}}

{{> inj.memory}}
```

**`blk.scope-fence`** -- scout investigation scope fence. Source: scout.py. Used
by: step.scout.1.

```text
## Project Directory

The project root is: `{{PROJECT_DIR}}`

All investigation MUST be scoped to this directory.
Do NOT search outside this path -- no `find /`, no `find ~`, no `/tmp`.
Always `cd` into the project directory or use absolute paths within it.

(multi-root variant when --add-dir is used: "## Project Roots" lists the primary
root + each additional dir, with the same scoping warning anchored at those roots.)
```

### 6.2 Shared body blocks (newly promoted)

These were duplicated across step bodies; promotion makes them single-source. Each
notes its **canonical** text and any **per-step variance** as a refactor target
(doc-first means the variance gets reconciled here, once).

**`blk.read-brief(when, why)`** -- read the frozen initiative context. Used by:
core-flows.1, tech-plan.1, milestone.1, plan.1, execute.1, curation.1.

```text
## Read initiative context

Read `brief.md` from the run directory {{when}}. It contains the frozen
initiative scope, decisions, and constraints from intake. {{why}}
```

> Variance to reconcile: tech-plan.1 and execute.1 fold a second artifact into
> `{{when}}` (core-flows.md / the executed plan); curation.1 makes the whole block
> conditional ("if `brief.md` exists"). Model the second-artifact case as an
> optional `also` param rather than overloading `when`.

**`blk.consult-memory(topic, example, closing?)`** -- consult project memory
before codebase work. Used by: intake.1, core-flows.1, tech-plan.1, plan.1,
milestone.1.

```text
## Consult project memory

Before reading any codebase file, check what the project already knows about
{{topic}}. Memory may contain decisions, conventions, procedures, and
constraints that shape your work here.

If relevant memory entries appeared above (`## Relevant memory`), read them now.

Then run `koan_reflect` with a broad question about {{topic}} (e.g. '{{example}}').
Use `koan_search` for specific decisions or procedures you need to respect.
{{? closing}}

{{closing}}
{{/closing}}
```

> Variance: intake.1 carries a longer, scout-planning framing ("Before planning
> scouts or direct reading...") and numbers the heading `## 3.`. Decide whether
> intake keeps a richer variant (a `framing` param) or conforms to the canonical.

**`blk.no-writes(what)`** -- the no-writes-this-step guard. Used by: intake.1,
intake.2, core-flows.1, tech-plan.1, milestone.1, plan.1, execute.1.

```text
Read and analyze before writing. Do NOT write {{what}} in this step.
```

> Variance: execute.1 phrases it "Do NOT write an assessment yet. Verify first."
> -- model as `what="an assessment yet"` plus an optional trailing imperative.

**`blk.reviewer-reconcile(artifact, reviewer, sidecar)`** -- reconcile the
mechanical reviewer's findings after `koan_artifact_write`. Used by: tech-plan.2,
milestone.2, plan.2.

````text
## Reconcile reviewer findings (inline, after write returns)

Once `koan_artifact_write` returns, you have the {{reviewer}}'s freeform findings.
Judge each finding and act:

- **Valid finding**: incorporate it by editing {{artifact}} in place via `koan_artifact_edit`.
- **Reviewer misconception**: overrule it by editing to add the missing context.
- **Approach-invalidating finding**: escalate via `koan_ask_question`.

Then append a per-finding disposition to the sidecar:

```
koan_artifact_edit(
    filename="{{sidecar}}",
    old_string="## Plan review (pre-exec)",
    new_string="""## Plan review (pre-exec)

### Orchestrator disposition

- Finding 1: [INCORPORATED / OVERRULED / ESCALATED] -- <rationale>
""",
)
```
````

> Variance: plan.2 adds two clarifying clauses ("the plan is still a draft; edits
> are allowed"; "before proceeding -- do not silently discard a finding that
> invalidates the whole approach"). Fold as optional emphasis or accept as canonical.

**`blk.curation-header(step)`** -- the workflow-shape / goal / tools-this-step
header rendered at the top of both curation steps. Source: curation.py
(`_header`). Used by: curation.1, curation.2. (Verbatim body migrated in the
consolidation pass; it is ~40 lines of `<workflow_shape>` / `<goal>` /
`<tools_this_step>` text, parameterized only by which step is "YOU ARE HERE".)

**`blk.curation-writing-rules`** -- the writing discipline, per-type guidelines,
title rules, contrastive examples, and the 9-item draft-quality checklist. Used
by: role.curation (references it) and curation.2 (renders it at the drafting
moment). This is the single place to fix the "8-item vs 9-item" inconsistency.
(Large verbatim block; migrated in the consolidation pass.)

### 6.3 Role contexts (verbatim migrated in consolidation)

One per orchestrator phase; prepended to step 1 by the assembly layer. Executor
and scout have none (identity = their system prompt); reviewer uses a charter.

| Fragment          | Used by phase | Source                          |
| ----------------- | ------------- | ------------------------------- |
| `role.intake`     | intake        | `koan/phases/intake.py`         |
| `role.core-flows` | core-flows    | `koan/phases/core_flows.py`     |
| `role.tech-plan`  | tech-plan     | `koan/phases/tech_plan_spec.py` |
| `role.milestone`  | milestone     | `koan/phases/milestone_spec.py` |
| `role.plan`       | plan          | `koan/phases/plan_spec.py`      |
| `role.execute`    | execute       | `koan/phases/execute.py`        |
| `role.curation`   | curation      | `koan/phases/curation.py`       |
| `role.frame`      | frame         | `koan/phases/frame.py`          |

> Several role contexts embed shared sub-blocks that are promotion candidates --
> e.g. `role.core-flows` and `role.tech-plan` both carry the identical "Mermaid
> syntax hazards" paragraph (promote to `blk.mermaid-hazards`), and the visualization
> slot/suppression rules. Flagged for the consolidation pass.

### 6.4 System prompts (verbatim migrated in consolidation)

| Fragment           | Delivered to      | Source                         |
| ------------------ | ----------------- | ------------------------------ |
| `sys.orchestrator` | the orchestrator  | `koan/prompts/orchestrator.py` |
| `sys.executor`     | executor subagent | `koan/prompts/executor.py`     |
| `sys.reviewer`     | reviewer subagent | `koan/prompts/reviewer.py`     |
| `sys.scout`        | scout subagent    | `koan/prompts/scout.py`        |

Shared sub-fragments to promote out of the system prompts (each appears in 2+):

| Sub-fragment            | Appears in                                              |
| ----------------------- | ------------------------------------------------------- |
| `blk.project-memory-ro` | sys.orchestrator, sys.executor, sys.reviewer, sys.scout |
| `blk.subagent-loop`     | sys.reviewer, sys.scout                                 |
| `blk.final-text-output` | sys.reviewer, sys.scout                                 |
| `blk.fresh-context`     | sys.reviewer, charter.plan/.milestone/.tech-plan        |

### 6.5 Charters (verbatim migrated in consolidation)

Per-family reviewer charter, injected at the top of step.reviewer.1 by
`{{reviewer_prompt}}`. Source: `koan/phases/reviewer.py`.

| Fragment            | Selector tag         | Reviews        |
| ------------------- | -------------------- | -------------- |
| `charter.plan`      | `PLAN_REVIEWER`      | plan artifacts |
| `charter.milestone` | `MILESTONE_REVIEWER` | milestones.md  |
| `charter.tech-plan` | `TECH_PLAN_REVIEWER` | tech-plan.md   |
| `charter.generic`   | (fallback)           | unknown family |

Shared: all three named charters end with `blk.report-only` ("You are read-only.
You report your findings; the orchestrator decides..."). Promote.

### 6.6 Guidance injections (verbatim migrated in consolidation)

The `{{PHASE_INSTRUCTIONS}}` content. Per-workflow content (the only place
workflow-specific text lives), except the two curation directives which are
shared. Source: `koan/lib/workflows.py`.

| Fragment                 | Injected at (workflow.phase)          | Notes                        |
| ------------------------ | ------------------------------------- | ---------------------------- |
| `g.plan.intake`          | plan.intake                           |                              |
| `g.plan.plan`            | plan.plan                             | one line ("Use plan.md ...") |
| `g.plan.execute`         | plan.execute                          |                              |
| `g.milestones.intake`    | milestones.intake                     |                              |
| `g.milestones.milestone` | milestones.milestone                  |                              |
| `g.milestones.plan`      | milestones.plan                       |                              |
| `g.milestones.execute`   | milestones.execute                    |                              |
| `g.initiative.intake`    | initiative.intake                     |                              |
| `g.initiative.coreflows` | initiative.core-flows                 |                              |
| `g.initiative.techplan`  | initiative.tech-plan                  |                              |
| `g.initiative.milestone` | initiative.milestone                  |                              |
| `g.initiative.plan`      | initiative.plan                       |                              |
| `g.initiative.execute`   | initiative.execute                    |                              |
| `g.discovery.frame`      | discovery.frame                       |                              |
| `g.postmortem`           | {plan,milestones,initiative}.curation | **shared** (3 workflows)     |
| `g.standalone`           | curation.curation                     |                              |

> The intake/execute guidance strings across workflows are near-parallel (scope +
> downstream + investigation posture + question posture + user override). Strong
> candidate for a parameterized `g.intake(scope, downstream, scouts, rounds)`
> rather than three hand-maintained copies -- flagged for consolidation.

Retrieval directives (`r.*`) parameterize `inj.memory`; they are short query
strings owned by the binding. Catalogued with their workflows in
`koan/lib/workflows.py`; not reproduced here.

---

## 7. Assembly

How fragments + a step body render into the text a model actually receives. This
is the prompt analog of the design system's render pipeline: the doc stores the
pieces; the runtime composes them. The fully-assembled prompt is never written
out anywhere -- it is reconstructable from this recipe.

Source: `_step_phase_handshake_core` and `_step_within_phase_core` in
`koan/tools/koan_tools.py`; `format_step` in `koan/phases/format_step.py`.

### Step 1 of a phase (the handshake)

```
{StepName}
==========                       <- format_step header (title + "=" underline)

{{> role.<phase>}}               <- role context, prepended (empty for executor/scout/reviewer)

{{> blk.step1-head(...)}}        <- workflow line (intake/frame) + guidance heading
                                    + {{PHASE_INSTRUCTIONS}} + {{> inj.memory}}

<step-1 body>                    <- the unique + factored body from section 5

{{> foot.advance|foot.yield|foot.default}}   <- footer chosen by the binding's next_phase
```

Composition order is fixed by `_step_phase_handshake_core`: role context is
prepended; the memory block is computed once at this handshake; the footer is
chosen from `PhaseBinding.next_phase` (`foot.advance` if bound, else `foot.yield`;
`foot.default` only when the phase has more steps).

### Steps 2..N

```
{StepName}
==========

<step-N body>

{{> foot.default | foot.yield}}   <- foot.yield only on the terminal step
```

Role context and the memory block are **not** re-injected on later steps -- they
persist in the orchestrator's conversation. Only the body + footer are delivered.

### Subagent steps

Same `format_step` rendering, but the identity is the **system prompt**
(`sys.<role>`) delivered at spawn, not a prepended role context. The reviewer's
charter is injected into the step.reviewer.1 body (not the system prompt) because
it varies per artifact family.

### Runtime placeholders vs fragment includes

- `{{> name(...)}}` resolves at **doc/build time** -- it is a fragment include.
- `{{VAR}}` resolves at **runtime** -- a value the driver injects (`{{TASK_DESCRIPTION}}`,
  `{{PHASE_INSTRUCTIONS}}`, the retrieved memory entries, `{{RUN_DIR}}`, ...).
- `{{? x}} ... {{/x}}` is a conditional block (rendered only when `x` is present).

---

## 8. Rationale

The non-obvious WHYs, so a maintainer does not "simplify" a load-bearing choice.
(The design system's "Design Rationale" analog.)

- **brief.md is frozen at intake exit.** Downstream phases parse its structure and
  treat it as authoritative. A wrong assumption is corrected in a milestone Outcome
  or a chat note -- never by rewriting brief.md -- so the handoff contract stays stable.

- **intake forbids writing brief.md before the final step.** The write tool is
  available in every phase (capability is composed per phase, not per step), and
  `role.intake` foregrounds brief.md as "your output" -- so without an explicit
  guard the orchestrator jumps straight to the deliverable on turn 1, freezing a
  brief written before any investigation or dialogue. `step.intake.1` and `.2`
  therefore carry `blk.no-writes`, and `role.intake` states brief.md is written
  only in the Summarize step. This is the guard every sibling production phase
  (core-flows, tech-plan, milestone, plan) already had on its analyze step and
  intake alone lacked.

- **intake must not infer decisions.** intake describes what exists and what was
  said; it does not design. An unverified assumption that reaches a downstream phase
  becomes a silent defect, so the role context forbids inference, opinions, and
  scope definition outright.

- **Curation renders its writing rules at the drafting moment** (`blk.curation-writing-rules`
  appears in step 2, not just the role context). Verbal rules from a system prompt
  do not survive the distance to the write; the model's default register is timeless
  documentation prose, and the contrastive examples are the only thing that overrides it.

- **The curation per-batch loop emits a committed, visible artifact per substep**
  (draft -> self-critique checklist -> revise). Collapsing the substeps lets the
  model sandbag drafts to manufacture fake improvements; the explicit checklist output
  is the load-bearing quality gate.

- **The curation header repeats the workflow shape at every step.** Earlier runs saw
  the orchestrator confuse curation with intake-style exploration and reach "phase
  complete" without ever calling `koan_memorize`. The `<workflow_shape>`/`<goal>`/
  `<tools_this_step>` block re-establishes position at the moment of use.

- **milestone is CREATE-only.** The discard hook deletes `milestones.md` on every
  re-entry, so the phase always writes fresh from the codebase rather than patching a
  stale decomposition. There is no RE-DECOMPOSE mode.

- **The reviewer runs in a fresh context.** It must not inherit the author's
  assumptions; the whole value is independent doubt. Hence no shared conversation, no
  scouts (it verifies directly), and findings returned as text the orchestrator
  reconciles -- the reviewer never edits.

- **Execution conformance is the orchestrator's call, not the executor's exit code.**
  The execute phase's bash checks are authoritative; a clean executor exit can still
  be marked non-conforming. Review independence again.

- **The remediation cap is one automated attempt, prompt-driven.** A base plan gets one
  automatic remediation; a second failure escalates to the user. The registry still
  allows further remediations so the user can direct them after escalation -- the cap
  is guidance, not a hard gate.

- **Suppression rules render below-threshold slots as prose only** (no diagram, no
  marker, no "suppressed" placeholder). A marker is noise; the prose alone is the slot.

- **Knowledge flows downward (the prime directive).** Restated here because it is the
  rule most likely to erode: every upward reference is a future maintenance trap.

---

## 9. Conventions & maintenance

### Identifier scheme

`workflow` names are bare (`plan`). `phase` names are bare (`intake`). Steps are
`step.<phase>.<n>`. Fragments use the `6.` prefixes (`role.*`, `sys.*`, `g.*`,
`blk.*`, `foot.*`, `inj.*`, `env.*`, `charter.*`, `r.*`).

### Which tier is this? (decision tree)

1. Is it the text for one turn? -> **Step** (`step.<phase>.<n>`).
2. Is it reused by 2+ steps, or a named slot the assembly composes (footer, memory
   block, role context, guidance, system prompt, charter)? -> **Fragment** (section 6).
3. Does it sequence steps + own lifecycle? -> **Phase** (section 4).
4. Does it sequence phases + own transitions + per-phase bindings? -> **Workflow** (section 3).

### The promotion rule

- Block used by ONE step -> inline in that step's body (section 5).
- Block used by 2+ steps -> promote to a fragment (section 6); reference via `{{> }}`.
- A guidance string near-duplicated across workflows -> parameterize into one
  fragment with params, not N hand-maintained copies.

### Doc-first protocol

This doc is authoritative. To change a prompt: edit the fragment/step/phase here
**first**, then update the `.py` to match. A prompt change that lands in code
without a doc change is drift -- treat it as a bug.

### Protected (do not silently restructure)

- `koan/tools/tool_policy.py` -- the per-(role, phase) tool allowlists. Capability
  is construction-time; the model cannot call what it cannot see.
- `koan/lib/workflows.py` -- the workflow/binding registry (the organism wiring).
- The assembly recipe (`format_step`, `_step_phase_handshake_core`) -- changing slot
  order changes every prompt at once.

### Verification checklist (adding or changing a prompt)

- [ ] Edited the doc first; the `.py` is a mechanical mirror.
- [ ] The change sits in the correct tier (decision tree above).
- [ ] No upward reference: a step names no other phase/workflow; a phase names no workflow.
- [ ] Any block now used by 2+ steps was promoted to a fragment (not copy-pasted).
- [ ] Each touched step's **contract** (Context in / Produces / Purpose / Success /
      Failure) is filled, not left as TODO.
- [ ] ASCII only -- no smart quotes, em-dashes, or other unicode in prompt text.
- [ ] LLMs read/write markdown only; the driver owns JSON state (the file boundary).

### Known tier leaks (fix these)

- **`role.core-flows` names downstream phases** (`tech-plan-review`, `exec-review`)
  as readers of core-flows.md. That is a phase reaching up into workflow knowledge,
  and the named phases were removed in the M6 review collapse -- they no longer exist.
  Rewrite to describe the artifact's role without naming successors.
- **Duplicate "Mermaid syntax hazards" / visualization-slot rules** in `role.core-flows`
  and `role.tech-plan` -- promote to a shared `blk.mermaid-hazards` / `blk.viz-slots`.
- **Three near-parallel intake guidance strings** (`g.*.intake`) and the execute
  guidance trio -- candidates for one parameterized fragment each.

---

_Doc status: structure, steps (factored), and the structural/promoted fragments are
authored. The verbatim bodies for role contexts, system prompts, charters, and
guidance (6.3-6.6) are indexed and migrate from `prompt-inventory.md` in the
consolidation pass, after which the inventory is retired._
