# Milestone Design Principles

Design document for the milestones workflow. Defines what makes a sound
milestone, how to size them, and the grounding requirements that prevent
decompositions from drifting away from codebase reality.

## What a milestone is

A milestone is a coherent, independently-deliverable unit of work within a
broad initiative. It is the unit of planning and execution: each milestone
gets its own plan (`plan-milestone-N.md`), its own executor session, and its
own review. The milestones workflow loops through `plan-spec -> [plan-review]
-> execute -> exec-review -> milestone-spec (UPDATE)` for each milestone until
all are complete.

Milestones are NOT tasks, stories, or tickets. They are structural partitions
of a codebase change initiative, grounded in the actual dependency graph of the
code being modified.

## Soundness criteria

A sound milestone satisfies four properties. Each has an operational test that
can be applied during milestone-spec (CREATE mode) and verified during
milestone-review.

### 1. Independently deliverable (local-constraint property)

A local constraint can be fulfilled purely based on the results of milestone N.
A global constraint requires multiple milestones to be jointly satisfied.

**Operational test:** if the executor only implemented milestone N and then
stopped, would milestone N's stated outcome still hold? If the answer requires
milestone N+1 to land, then N is not independent.

### 2. Grounded in code structure

Code within a repository is inter-dependent. Milestones must decompose work
along dependency edges, not against them. A decomposition that slices across
strongly-connected components in the dependency graph guarantees integration
pain at milestone boundaries.

**Operational test:** map each milestone's scope to a set of files/modules. Do
the milestones partition the affected subgraph into connected subgraphs, or do
they slice across strongly-connected components? The latter is a structural
error.

### 3. Plannable within one plan-spec session

Plan-spec reads files, consults memory, and produces a `plan-milestone-N.md`.
Its context budget is bounded by the model's window minus the overhead of all
prior phases in the conversation.

**Operational test:** can plan-spec read every file the milestone touches (or
at least the interface files) and still have room to write a detailed
implementation plan? If a milestone touches 40+ files across multiple
subsystems, this probably fails.

### 4. Executable within one executor session

The executor runs on its own context window. Performance scales with model
capability but shows diminishing returns -- capacity is not unlimited.

**Operational test:** a plan of roughly 10-30 concrete implementation steps is
a rough ceiling for a single executor session before quality degrades. Plans
that exceed this should split.

## Sizing heuristics

The binding constraint on milestone size is the context capacity of downstream
phases, not developer attention or time estimates. An operational definition:

> A milestone is appropriately sized if (a) plan-spec can read all files
> relevant to the milestone's scope while still producing a specific
> implementation plan, and (b) the resulting plan fits in an executor session
> of roughly 10-30 implementation steps.

Practical heuristics for prompt guidance:

- **Files-touched heuristic:** roughly 5-30 files per milestone. Fewer means
  probably merge with a neighbor. More means probably split.
- **Plan-step heuristic:** the plan written for this milestone should be
  around 10-30 steps. If the decomposer can already see that a milestone
  will require 50+ steps, it is too large.
- **Description heuristic:** if the milestone sketch needs more than 6
  sentences to describe what it covers, it is probably doing too much.

## Grounding requirements

Milestone decomposition must be grounded against the actual code structure,
not performed in the abstract. The grounding process, in priority order:

1. **Read the project's module structure.** Not individual files -- structure.
   The directory tree, the top-level packages, the visible boundaries. This
   is the prior for where milestones should cut.

2. **Identify the affected subgraph.** From intake findings, identify which
   packages/modules the initiative touches. Read the import graph among those
   (or at least the outgoing imports from the entry points).

3. **Map each proposed milestone to a scope.** Every milestone's sketch should
   name the files or modules it owns. If a milestone's scope cannot be named
   in terms of existing code structure, either it is about a greenfield area
   (legitimate) or the decomposition is imaginary.

4. **Check for overlaps.** Two milestones that claim to own the same
   file/function are not independent. This is the local-constraint failure
   mode -- overlapping ownership means the milestones are not truly
   partitioned.

5. **Consult memory for past decomposition patterns.** Use `koan_reflect` (not
   just `koan_search`) for broad synthesis about subsystem boundaries and
   delivery sequencing patterns.

## Cross-milestone learning

When planning milestone N > 1, the orchestrator must carry forward what was
learned from prior milestone executions:

- Read the Outcome sections of all completed milestones in `milestones.md`.
  These describe what was actually built, including integration points,
  patterns, and constraints established by prior milestones.
- If Outcome sections reference specific files or interfaces that the current
  milestone will extend, read those files directly -- the code is the source
  of truth, not the prior plan.
- The orchestrator's conversation context is preserved across milestone
  cycles. Cross-milestone learning is about directing attention, not
  recovering lost context.

## The UPDATE cycle

After exec-review completes for a milestone, the orchestrator transitions back
to milestone-spec in UPDATE mode. The update cycle:

1. Read `milestones.md` and the exec-review assessment from conversation
   context.
2. Mark the completed milestone `[done]` and add an `### Outcome` section
   describing what was actually accomplished (not what was planned).
3. Adjust remaining milestones based on deviations: reorder, add, remove, or
   revise sketches as needed.
4. Mark the next `[pending]` milestone as `[in-progress]`.
5. If remaining milestones exist, transition to `plan-spec`.
6. If all milestones are `[done]` or `[skipped]`, transition to `curation`.

## Compound-risk framing

Errors at the milestone layer compound across every subsequent phase:

```
milestone decomposition error
  -> wrong scope in plan-spec -> wrong plan
    -> wrong execution -> wrong code
      -> wrong exec-review assessment
        -> wrong milestone update
          -> wrong next milestone plan
```

This is why milestone-review exists as a designated adversarial phase. See
[phase-trust.md](./phase-trust.md) for the trust model and verification
boundaries.
