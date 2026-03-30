# Intake Loop Design

How the intake phase implements a confidence-gated investigation loop, and the
prompt engineering principles that govern it.

> Parent doc: [architecture.md](./architecture.md)
> Related: [subagents.md -- Step-First Workflow](./subagents.md#step-first-workflow)

---

## Overview

The intake phase is the most consequential subagent in the pipeline. Its
single output -- `landscape.md` -- is the sole input for all downstream phases.
Every story boundary, every implementation plan, and every line of code
produced downstream depends on the completeness and accuracy of that file.
Gaps in `landscape.md` compound: a missed decision becomes a wrong story
boundary becomes a wrong plan becomes wrong code.

This weight justifies a more elaborate workflow than other phases. Rather than
a fixed sequence of steps, intake runs a **confidence-gated loop**: the LLM
scouts the codebase, enumerates what it knows, asks the user questions, and
then explicitly self-verifies its understanding. The loop repeats until the
LLM declares it is "certain" the decomposer has everything it needs.

### Step structure

| Step | Name       | Runs | Purpose                                                                            |
| ---- | ---------- | ---- | ---------------------------------------------------------------------------------- |
| 1    | Extract    | 1x   | Read conversation input. No side effects.                                          |
| 2    | Scout      | 1-4x | Dispatch codebase investigators.                                                   |
| 3    | Deliberate | 1-4x | Enumerate knowns/unknowns, ask user questions.                                     |
| 4    | Reflect    | 1-4x | Self-verify completeness, declare confidence.                                      |
| 5    | Synthesize | 1x   | Write `landscape.md`. Review gate: calls `koan_review_artifact` before completing. |

Steps 2-4 form the loop. Each call to `koan_complete_step` during these steps
either returns the next step in sequence or loops back from step 4 to step 2.
Steps 1 and 5 execute exactly once.

---

## Non-Linear Step Progression

### `get_next_step()` hook

The default step engine provides linear progression: `step+1` until
`total_steps`, then `None` (done). Phase modules override `get_next_step(step, ctx)`
to implement non-linear flows.

`koan/phases/intake.py` overrides this to implement the confidence gate:

```python
def get_next_step(step, ctx):
    """Pure query -- returns where to go, does not mutate state."""
    if step == 4:                          # Reflect step
        if confidence == "certain" or is_exhausted:
            return 5                       # -> Synthesize
        return 2                           # -> Scout (loop back)
    if step == 5:
        return None                        # Synthesize -> done
    return step + 1                        # linear for steps 1-3
```

```python
def on_loop_back(from_step, to_step, ctx):
    """Side effects of the loop-back decision live here, not in get_next_step()."""
    ctx.iteration += 1
    ctx.intake_confidence = None           # reset for next round
    emit_iteration_start(ctx.event_log, ctx.iteration, MAX_ITERATIONS)
```

`get_next_step()` is a **pure query** -- it only decides where to go. All side
effects (counter increments, state resets, event emission) belong in
`on_loop_back()`, which the step engine calls whenever `get_next_step()` returns
a step number less than the current one.

All other phase modules inherit the default linear behavior. The hook localizes
non-linear logic to the one module that needs it without touching other phases.

### `total_steps` semantics with a loop

For the intake phase, `total_steps = 5` reflects the number of distinct step
definitions, not the number of `koan_complete_step` calls. The loop may
execute steps 2-4 up to four times, producing up to 1 + (3 x 4) + 1 = 14
calls in the worst case.

---

## The Confidence Gate

### Why a separate tool, not a parameter

`koan_set_confidence` is a dedicated tool rather than a parameter on
`koan_complete_step` for two reasons:

1. **Optional parameters are skippable.** LLMs frequently omit optional
   parameters, especially when under token pressure. A separate tool call is
   harder to skip accidentally.

2. **`koan_complete_step` is shared across all phases.** Adding confidence to
   it would bloat the parameter schema for roles that never set confidence.
   A dedicated `koan_set_confidence` tool, restricted to the intake role via
   permissions, keeps the boundary clean.

### Mandatory enforcement via `validate_step_completion()`

The step engine calls `validate_step_completion(step, ctx)` before
`get_next_step()`. It returns None to allow advancement or an error string that
is returned as the `koan_complete_step` tool result -- the LLM sees it and
must fix the pre-condition before retrying.

The intake phase uses this to enforce that `koan_set_confidence` was called in
the Reflect step:

```python
def validate_step_completion(step, ctx):
    if step == 4 and ctx.intake_confidence is None:
        return "You must call koan_set_confidence before completing the Reflect step."
    return None
```

### Confidence reset on loop-back

When `get_next_step()` returns step 2 (loop-back), the step engine detects the
backward transition and calls `on_loop_back()`. The intake module's
`on_loop_back()` resets `ctx.intake_confidence = None`. This ensures that in
the next Reflect step, the LLM must call `koan_set_confidence` again.

### Maximum iterations

The loop is bounded at 4 iterations. When exhausted, `get_next_step()` returns
step 5 (Synthesize) instead of step 2. This prevents infinite loops if the LLM
consistently declares non-certain confidence.

---

## Step-Aware Permission Gating

The permission fence in `koan/lib/permissions.py` accepts the current step
context and blocks specific tools during steps where they would undermine the
workflow.

### Step 1 (Extract): read-only

Step 1 should only read the conversation. Without a mechanical gate, the LLM
frontloads all work into step 1.

`check_permission()` blocks all side-effecting tools when
`role == "intake" and intake_step == 1`:

```
koan_request_scouts, koan_ask_question, koan_set_confidence, write, edit
```

### Step 3 (Deliberate): no confidence assessment

Step 3 is for enumerating knowns/unknowns and asking questions. Confidence
assessment belongs exclusively in step 4 (Reflect).

`check_permission()` blocks `koan_set_confidence` when
`role == "intake" and intake_step == 3`.

### Prompt + enforcement is not redundant

The prompt tells the LLM not to use side-effecting tools in step 1 and not
to assess confidence in step 3. The permission gates are fallbacks that catch
prompt non-compliance. Together: the prompt prevents the behavior; the gate
catches it when the prompt fails.

---

## Audit Events and SSE Propagation

Two audit event types support UI visualization of confidence and iteration:

| Event               | Emitted by                         | When                              |
| ------------------- | ---------------------------------- | --------------------------------- |
| `confidence_change` | `koan_set_confidence` tool         | Every call to koan_set_confidence |
| `iteration_start`   | `on_loop_back()` + step transition | At every loop iteration start     |

Both events are folded into the `state.json` projection:

- `confidence_change` -> `intake_confidence`, `intake_iteration`
- `iteration_start` -> `intake_iteration`

Audit events are pushed directly from the tool handlers and step engine -- no
polling loop. Browser-visible intake state (current phase, confidence level) is
derived from `agent_step_advanced` and `phase_started` projection events, which
the frontend renders from the Zustand store.

---

## Prompt Engineering Principles

The intake loop prompts apply several techniques from the prompting literature.
This section records the reasoning so future changes don't inadvertently remove
mechanisms that address specific failure modes.

### Prompt Chaining over Stepwise (Scout / Deliberate / Reflect as separate steps)

A monolithic "investigate" step is rejected in favor of three separate
`koan_complete_step` calls. The risk with a monolithic step is **simulated
refinement**: the LLM artificially degrades its initial output to manufacture
visible improvement. Separate steps enforce genuinely isolated reasoning.

### Thread-of-Thought in Deliberate (explicit enumeration before questions)

The Deliberate step instructs the LLM to walk through each area and explicitly
state what is known, unknown, and its source -- before formulating questions.
This surfaces gaps that are not top-of-mind.

### Anticipatory Reflection in Deliberate (downstream impact assessment)

Between enumeration and question formulation, the Deliberate step includes a
downstream impact assessment. Each unknown is classified as ASK (user input
needed), SCOUT (follow-up can resolve), or SAFE (implementation detail).

### Default-ask question framing (preventing question avoidance)

The Deliberate step frames question-asking as the default, with skipping
requiring triple justification. This inverts the typical LLM bias toward
advancing the workflow.

### Chain-of-Verification in Reflect (evidence-grounded self-assessment)

The Reflect step instructs the LLM to generate 3-5 verification questions
framed from the decomposer's perspective, then answer each using only concrete
evidence. This is the Chain-of-Verification (CoVe) pattern.

### Contrastive confidence definitions (preventing premature "certain")

The Reflect step provides both positive ("certain means ALL of these are true")
and negative ("you are NOT certain if ANY of these are true") definitions.
The negative examples make failure modes concrete and explicit.

### Stakes framing (EmotionPrompt for accountability)

The system prompt includes: "A question you don't ask is an answer you're
making up." This connects intake shortcuts directly to downstream failures.

### Iteration-aware guidance (first iteration vs. refinement)

Steps 2 (Scout) and 3 (Deliberate) produce different instruction text for
the first iteration vs. subsequent iterations. This prevents the LLM from
repeating its initial exploration.

### Iteration expectations (soft minimum via GIoT)

The Reflect step includes soft guidance that round 1 should rarely produce
"certain" confidence. This provides directional pressure without forcing
unnecessary iterations on trivial tasks.

---

## Pitfalls

### Don't put confidence in koan_complete_step's `thoughts` parameter

`thoughts` is an escape hatch for models that can't mix text + tool_call.
Parsing it for routing decisions would violate driver determinism. Confidence
must flow through a structured tool call.

### Don't rely on the Reflect prompt alone to enforce koan_set_confidence

The `validate_step_completion()` hook is the mechanical enforcement layer.
Both prompt and hook must be present.

### Don't remove the confidence null-reset on loop-back

Without this reset, `validate_step_completion()` sees the old confidence value
and allows advancement without the LLM calling `koan_set_confidence` again.
The reset must happen in `on_loop_back()`, not in `get_next_step()`.

### Don't add koan_set_confidence to non-intake roles

`koan_set_confidence` is gated to the intake role via permissions.

### Don't allow koan_set_confidence during Deliberate (step 3)

Without this gate, the LLM sets confidence during Deliberate, anchoring the
subsequent Reflect step toward "certain". Confidence assessment must happen
only during Reflect (step 4).

### Don't make the "NOT certain" checklist vacuously satisfiable

Every condition must be non-vacuously testable. Prefer conditions that require
positive evidence: "you have not asked any questions" is mechanically true or
false based on whether `koan_ask_question` was called.

### Don't skip step sync on loop-back

The permission gate reads the current step at tool call time. If the step
context is not updated on loop-back, gates fire at the wrong step.
