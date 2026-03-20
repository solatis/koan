# Intake Loop Design

How the intake phase implements a confidence-gated investigation loop, and the
prompt engineering principles that govern it.

> Parent doc: [architecture.md](./architecture.md)
> Related: [subagents.md § Step-First Workflow](./subagents.md#step-first-workflow-basephase)

---

## Overview

The intake phase is the most consequential subagent in the pipeline. Its
single output — `context.md` — is the sole input for all downstream phases.
Every story boundary, every implementation plan, and every line of code
produced downstream depends on the completeness and accuracy of that file.
Gaps in `context.md` compound: a missed decision becomes a wrong story
boundary becomes a wrong plan becomes wrong code.

This weight justifies a more elaborate workflow than other phases. Rather than
a fixed sequence of steps, intake runs a **confidence-gated loop**: the LLM
scouts the codebase, enumerates what it knows, asks the user questions, and
then explicitly self-verifies its understanding. The loop repeats until the
LLM declares it is "certain" the decomposer has everything it needs.

### Step structure

| Step | Name | Runs | Purpose |
|------|------|------|---------|
| 1 | Extract | 1× | Read `conversation.jsonl`. No side effects. |
| 2 | Scout | 1–4× | Dispatch codebase investigators. |
| 3 | Deliberate | 1–4× | Enumerate knowns/unknowns, ask user questions. |
| 4 | Reflect | 1–4× | Self-verify completeness, declare confidence. |
| 5 | Synthesize | 1× | Write `context.md`. |

Steps 2–4 form the loop. Each call to `koan_complete_step` during these steps
either returns the next step in sequence or loops back from step 4 to step 2.
Steps 1 and 5 execute exactly once.

---

## Non-Linear Step Progression

### `getNextStep()` hook

The `BasePhase` class previously used a hardcoded linear counter:
`step+1` until `totalSteps`, then `null` (done). This was extended with a
`getNextStep(currentStep)` hook that subclasses override to implement
non-linear flows.

```typescript
// Default: strictly linear.
protected getNextStep(currentStep: number): number | null {
  if (currentStep === this.totalSteps) return null;
  return currentStep + 1;
}
```

`IntakePhase` overrides this to implement the confidence gate:

```typescript
// Pure query — returns where to go, does not mutate state.
protected getNextStep(currentStep: number): number | null {
  if (currentStep === 4) {                          // Reflect step
    if (confidence === "certain" || isExhausted) {
      return 5;                                     // → Synthesize
    }
    return 2;                                       // → Scout (loop back)
  }
  if (currentStep === 5) return null;               // Synthesize → done
  return currentStep + 1;                           // linear for steps 1–3
}

// Side effects of the loop-back decision live here, not in getNextStep().
protected override async onLoopBack(_from: number, _to: number): Promise<void> {
  this.iteration++;
  this.ctx.intakeConfidence = null;                 // reset for next round
  await this.eventLog?.emitIterationStart(this.iteration, MAX_ITERATIONS);
}
```

`getNextStep()` is a **pure query** — it only decides where to go. All side
effects (counter increments, state resets, event emission) belong in
`onLoopBack()`, which `BasePhase.handleStepComplete()` calls whenever
`getNextStep()` returns a step number less than the current one. This
separation makes `getNextStep()` safe to reason about and test in isolation.

All other phase classes inherit the default linear behavior. The hook localizes
non-linear logic to the one class that needs it without touching other phases.

**Why not a separate loop-phase class?** The `BasePhase` machinery (boot
transition, permission fence, event logging, step formatting) is the same
regardless of whether progression is linear or not. A hook is cheaper than a
new abstraction tier and does not require refactoring the six existing phase
classes.

### `totalSteps` semantics with a loop

For `IntakePhase`, `totalSteps = 5` reflects the number of distinct step
definitions, not the number of `koan_complete_step` calls. The loop may
execute steps 2–4 up to four times, producing up to 1 + (3 × 4) + 1 = 14
calls in the worst case. The `step_transition` event carries both the step
number and the iteration-annotated step name (e.g., "Scout (round 3)") so the
UI can distinguish loop iterations.

---

## The Confidence Gate

### Why a separate tool, not a parameter

An earlier design considered adding `confidence` as an optional parameter to
`koan_complete_step`. This was rejected for two reasons:

1. **Optional parameters are skippable.** LLMs frequently omit optional
   parameters, especially when under token pressure. A separate tool call is
   harder to skip accidentally — the LLM must make an explicit decision.

2. **`koan_complete_step` is shared across all phases.** Adding confidence to
   it would either bloat the parameter schema for roles that never set
   confidence, or require conditional schema logic that the permission fence
   cannot express cleanly. A dedicated `koan_set_confidence` tool, restricted
   to the intake role via `ROLE_PERMISSIONS`, keeps the boundary clean.

### Mandatory enforcement via `validateStepCompletion()`

`BasePhase` exposes a `validateStepCompletion(step)` hook that runs before
`getNextStep()`. It returns null to allow advancement or an error string that
is returned as the `koan_complete_step` tool result — the LLM sees it and
must fix the pre-condition before retrying.

`IntakePhase` uses this to enforce that `koan_set_confidence` was called in
the Reflect step:

```typescript
protected async validateStepCompletion(step: number): Promise<string | null> {
  if (step === 4 && this.ctx.intakeConfidence === null) {
    return "You must call koan_set_confidence before completing the Reflect step. ...";
  }
  return null;
}
```

This is mechanical enforcement on top of the prompt-level instruction. If the
LLM ignores the prompt and calls `koan_complete_step` without first calling
`koan_set_confidence`, it receives an error and must comply.

### Confidence reset on loop-back

When `getNextStep()` returns step 2 (loop-back), `BasePhase` detects the
backward transition and calls `onLoopBack()`. `IntakePhase.onLoopBack()`
resets `ctx.intakeConfidence = null`. This ensures that in the next Reflect
step, the LLM must call `koan_set_confidence` again — carry-over from the
previous iteration is not possible.

Without the reset, a LLM that set confidence to "high" in iteration 1 could
call `koan_complete_step` in iteration 2's Reflect step without reassessing,
and `validateStepCompletion` would let it through.

**Note:** The audit projection's `intakeConfidence` field is updated only when
a `confidence_change` event is appended (i.e., when `koan_set_confidence` is
called). Between loop-back and the next Reflect step, the projection still
shows the previous iteration's confidence level. This is intentional: the
projection reflects the last declared state, not the reset internal state. The
UI reads the projection, so it shows the previous confidence until a new one
is declared.

### Maximum iterations

The loop is bounded at 4 iterations (`IntakePhase.MAX_ITERATIONS`). When
exhausted, `getNextStep()` returns step 5 (Synthesize) instead of step 2.
`IntakePhase` logs a warning when this forced exit occurs. This prevents
infinite loops if the LLM consistently declares non-certain confidence.

---

## Step-Aware Permission Gating

### Why step 1 is mechanically read-only

Step 1 (Extract) should only read the conversation. Before this redesign, step
isolation was enforced only through prompt instructions ("do NOT call
koan_request_scouts in this step"). The LLM frequently violated this by
frontloading all work into step 1, leading to duplicate scout requests in
later steps.

The new design adds a mechanical layer: `checkPermission()` accepts an
optional `intakeStep` parameter and blocks a defined set of tools when
`role === "intake" && intakeStep === 1`:

```
koan_request_scouts, koan_ask_question, koan_set_confidence, write, edit
```

The current step is propagated via `ctx.intakeStep`, kept in sync by the
`onStepUpdated()` hook in `IntakePhase`:

```typescript
protected onStepUpdated(step: number): void {
  this.ctx.intakeStep = step;
  this.ctx.intakeIteration = this.iteration;
}
```

`BasePhase.handleStepComplete()` calls `onStepUpdated()` on every step
transition (including loop-backs), so `ctx.intakeStep` always reflects the
current active step at tool call time.

### Prompt + enforcement is not redundant

The prompt still tells the LLM not to use side-effecting tools in step 1.
The permission gate is a fallback that catches prompt non-compliance. Together:
the prompt prevents the behavior; the gate catches it when the prompt fails.
Neither alone is sufficient — the prompt can be ignored; the gate with no
prompt would produce confusing "blocked" errors with no context for the LLM.

---

## Audit Events and SSE Propagation

Two new audit event types support UI visualization of confidence and iteration:

| Event | Emitted by | When |
|-------|-----------|------|
| `confidence_change` | `koan_set_confidence` tool | Every call to koan_set_confidence |
| `iteration_start` | `IntakePhase.onLoopBack()` + `onStepUpdated()` | At every loop iteration start: `onLoopBack` for iterations 2+, `onStepUpdated` for iteration 1 |

Both events are folded into the `state.json` projection:

- `confidence_change` → `intakeConfidence`, `intakeIteration`
- `iteration_start` → `intakeIteration`

The web server polls `state.json` every 50ms for each active agent. When it
detects a change in `intakeConfidence` or `intakeIteration`, it pushes an
`intake-progress` SSE event to connected browser clients. The event payload
includes both the `confidence` string and the `iteration` number, allowing the
UI to render a progress visualization without maintaining its own state.

The `confidence_change` event requires `ctx.eventLog` to be set. This is
populated in `extensions/koan.ts` during `before_agent_start`, after
`eventLog.open()`. The confidence tool reads `ctx.eventLog` at call time
(mutable-ref pattern) — no reference is needed at registration time.

---

## Prompt Engineering Principles

The intake loop prompts apply several techniques from the prompting literature.
This section records the reasoning so future changes don't inadvertently remove
mechanisms that address specific failure modes.

### Prompt Chaining over Stepwise (Scout / Deliberate / Reflect as separate steps)

A monolithic "investigate" step — containing scouting, deliberation, and
reflection in sequence within a single prompt — was rejected in favor of three
separate `koan_complete_step` calls.

The risk with a monolithic step is **simulated refinement**: the LLM
artificially degrades its initial output to manufacture visible improvement.
When draft, critique, and refine happen in one cognitive context, the model
sandbaggs the draft to make its self-correction look meaningful. When each
phase is a separate tool call with a distinct cognitive goal, the model must
genuinely complete each phase before seeing the next instruction. There is no
opportunity to pre-plan the "improvement" because the next step's instructions
are not yet visible.

This is why Scout, Deliberate, and Reflect are separate steps rather than
phases within a single step.

### Thread-of-Thought in Deliberate (explicit enumeration before questions)

The Deliberate step instructs the LLM to walk through each area relevant to
the task and explicitly state what is known, unknown, and its source — before
formulating questions. This is the Thread-of-Thought pattern: "walk through
this context in manageable parts step by step, summarizing and analyzing as we
go."

Without this enumeration, the LLM tends to ask questions based on what
immediately comes to mind rather than what is actually unknown. Gaps that are
not top-of-mind are missed. Forcing explicit enumeration of knowns and unknowns
before question formulation surfaces those gaps and prevents asking questions
the conversation or scouts already answered.

The enumeration also has a secondary benefit in iteration 2+: it forces the
LLM to re-state updated understanding before forming follow-up questions,
preventing the "lost in the middle" problem where findings from early scout
tool results are effectively forgotten by the time questions are formulated.

### Chain-of-Verification in Reflect (evidence-grounded self-assessment)

The Reflect step instructs the LLM to generate 3–5 verification questions
framed from the decomposer's perspective, then answer each using only concrete
evidence (quotes from conversation, specific scout findings, explicit user
answers). Verification questions that cannot be answered with evidence identify
gaps. This is the Chain-of-Verification (CoVe) pattern.

The framing matters: "from the decomposer's perspective" anchors the LLM's
self-assessment to the actual consumer of its output. Without this framing, the
LLM tends to ask generic comprehension questions ("do I understand the topic?")
rather than boundary-defining questions ("could I define the scope of story 1
vs story 2 right now?"). Generic questions produce generic assessments;
boundary-specific questions surface the gaps that actually matter downstream.

This is explicitly NOT intrinsic self-correction, which degrades reasoning
performance when no external feedback source is available. The LLM is not
being asked to critique its reasoning — it is being asked to generate specific
verification questions and answer them against gathered evidence. The evidence
is external (conversation, scouts, user answers), not the LLM's own reasoning.

### Contrastive confidence definitions (preventing premature "certain")

The Reflect step provides two contrastive definitions of the "certain"
confidence level:

- **Positive:** "certain means ALL of these are true" (four specific
  conditions about scope, codebase knowledge, user decisions, and story
  immutability)
- **Negative:** "you are NOT certain if" (four failure modes that preclude
  certainty)

This is the Contrastive Chain-of-Thought pattern. A single positive definition
("certain means you have everything you need") leaves the LLM to interpret what
"everything" means — and LLMs tend to interpret this charitably, setting
confidence to "certain" prematurely to exit the loop faster (token-saving
behavior). The negative examples make the failure modes concrete and explicit,
raising the bar for claiming certainty.

### Iteration-aware guidance (first iteration vs. refinement)

Steps 2 (Scout) and 3 (Deliberate) produce different instruction text for
the first iteration vs. subsequent iterations. First-iteration Scout says:
"Based on your reading of the conversation..." Subsequent Scout says: "Based
on gaps identified in your previous reflection..."

This is context reframing. The first iteration is an initial exploration; the
second iteration is a targeted follow-up. If both iterations received the same
prompt, the LLM would repeat its initial exploration rather than narrowing in
on the gaps surfaced by reflection. The iteration number is passed as a
parameter to `intakeStepGuidance()`, which branches on it to produce the
appropriate framing.

---

## Pitfalls

### Don't put confidence in koan_complete_step's `thoughts` parameter

`thoughts` is for internal chain-of-thought reasoning. A previous design
considered parsing confidence from the thoughts string. This violates the
driver determinism invariant: the driver never parses free-text. Confidence
must flow through a structured tool call with a typed parameter.

### Don't rely on the Reflect prompt alone to enforce koan_set_confidence

The Reflect step prompt ends with "WHEN DONE: First call koan_set_confidence,
then call koan_complete_step." This is a prompt instruction and can be ignored.
The `validateStepCompletion()` hook is the mechanical enforcement layer. Both
must be present: the prompt tells the LLM what to do; the hook catches
non-compliance.

### Don't remove the confidence null-reset on loop-back

The null-reset lives in `onLoopBack()` in `IntakePhase`. When looping from
step 4 → step 2, `ctx.intakeConfidence` must be set to null. Without this
reset, the `validateStepCompletion()` check in the next Reflect step sees the
old confidence value and allows `koan_complete_step` through without the LLM
calling `koan_set_confidence` again.

The reset must happen in `onLoopBack()`, not in `getNextStep()`. Placing it
in `getNextStep()` would make the query impure — see
[architecture.md § Don't put side effects in getNextStep()](./architecture.md#dont-put-side-effects-in-getnextstep).

### Don't add koan_set_confidence to non-intake roles

`koan_set_confidence` is gated to the intake role via `ROLE_PERMISSIONS`. If
it were available to other roles, they could set `ctx.intakeConfidence`
spuriously, affecting the intake loop's behavior if intake is running
concurrently (which it isn't currently, but could be in the future).

### Don't skip `ctx.intakeStep` sync in onStepUpdated

The permission gate reads `ctx.intakeStep` at tool call time. If
`onStepUpdated()` were not called on loop-back (step 4 → step 2), step 2
would execute with `ctx.intakeStep = 4`, and the step-1 gate would not fire
(step 4 ≠ 1). The step 1 gate is specifically `intakeStep === 1`. Only step 1
needs gating, so the only critical sync is the boot → step 1 transition. But
keeping `ctx.intakeStep` accurate at all times makes the invariant easier to
reason about and avoids subtle bugs if the gating logic is ever extended.
