# Epic Brief

The epic brief is a compact product-level artifact produced between intake and
core-flows. It captures the **what and why** of an epic and serves as a
correctness anchor for all downstream phases.

> Related: [artifact-review.md](./artifact-review.md) -- the mechanism used
> to present brief.md for human review before pipeline advancement.

---

## What It Captures

| Section               | Content                                                                 |
| --------------------- | ----------------------------------------------------------------------- |
| **Summary**           | 3-8 sentences: what this epic is about                                  |
| **Context & Problem** | Who is affected, where in the product, what the current pain is         |
| **Goals**             | Numbered list of measurable objectives                                  |
| **Constraints**       | Hard constraints from landscape.md (technical, timeline, compatibility) |

**Size constraint:** Under 50 lines. The brief is consulted by the core-flows
phase, planner, and orchestrator on every pipeline run -- compact size ensures
it remains a quick reference rather than a specification to read in full.

## What It Excludes

- UI flows and wireframes
- Technical architecture decisions
- Implementation details
- Story decomposition

These belong in later artifacts (story sketches, `plan/context.md`).

---

## Pipeline Position

```
intake -> brief-generation -> core-flows -> tech-plan -> ticket-breakdown -> cross-artifact-validation -> execution -> implementation-validation
```

The brief sits between intake and core-flows:

- **After intake:** `landscape.md` is complete. The brief distills this into a
  problem statement.
- **Before core-flows:** Downstream phases read `brief.md` to scope work
  against stated goals and constraints.

---

## Brief-Writer Subagent

Role: `"brief-writer"`. Model tier: `"strong"` (synthesis from intake context
requires genuine reasoning).

### Step Progression

```
Boot -> koan_complete_step (step 0 -> 1)

Step 1 (Read):
  Read landscape.md. Build mental model. No file writes allowed.

Step 2 (Draft & Review):
  Write brief.md. Call koan_review_artifact.
  If feedback -> revise brief.md, call koan_review_artifact again.
  If "Accept" -> call koan_complete_step.
  [Loops within step 2 until user accepts]

Step 3 (Finalize):
  Phase complete.
```

**Review gate:** `validate_step_completion(step=2)` in
`koan/phases/brief_writer.py` requires at least one `koan_review_artifact` call
before `koan_complete_step` is allowed.

### Permissions

```python
# koan/lib/permissions.py
"brief-writer": {
    "koan_complete_step",
    "koan_review_artifact",
    "edit",
    "write",
    # No koan_ask_question -- uses artifact review, not structured questions.
    # No koan_request_scouts -- all codebase context arrives via landscape.md.
}
```

Write/edit access is path-scoped to the epic directory.

---

## Downstream References

All planning phases are prompted to read `brief.md` before acting:

| Phase                           | Why                                                                     |
| ------------------------------- | ----------------------------------------------------------------------- |
| **Core-flows and later phases** | Scope work against brief goals; must not invent scope absent from brief |
| **Planner**                     | Plans must serve product-level goals and respect constraints            |
| **Orchestrator**                | Validates story completion against product goals                        |

The executor reads `plan/context.md` (story-level context) and does not
consult the epic brief directly.

---

## Design Rationale

### Artifact cascade

Each phase produces an artifact that downstream phases consult:

```
landscape.md        (intake synthesis)
  -> brief.md         (problem + goals + constraints)
    -> core-flows.md  (user journeys)
      -> story.md x N  (ticket-breakdown)
      -> plan/context.md x N  (story plans)
```

Each artifact is progressively more specific.

### Why a separate brief phase

A merged "brief + core-flows" agent would violate the single-cognitive-goal
principle. Separating them:

- Forces the brief to be reviewed and accepted before core-flows begins
- Prevents downstream phases from anchoring on their own interpretation of scope
- Creates a reviewable artifact that can be corrected before downstream work starts
