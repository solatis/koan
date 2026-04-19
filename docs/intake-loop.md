# Intake Phase Design

How the intake phase gathers context in three steps, and the prompt
engineering principles that govern it.

> Parent doc: [architecture.md](./architecture.md)
> Related: [subagents.md -- Step-First Workflow](./subagents.md#step-first-workflow)

---

## Overview

The intake phase is the most consequential phase in the pipeline. Its
output -- verified understanding of the task and codebase -- is the foundation
for all downstream phases. Every implementation plan and every line of code
produced downstream depends on the completeness and accuracy of what intake
discovers. Gaps compound: a missed decision becomes a wrong plan becomes
wrong code.

The intake phase runs a focused **three-step workflow**: gather context
(conversation + codebase orientation + scouts), deepen understanding through
dialogue and codebase verification, then synthesize findings into a handoff
summary.

### Step structure

| Step | Name      | Runs | Purpose                                                                  |
| ---- | --------- | ---- | ------------------------------------------------------------------------ |
| 1    | Gather    | 1x   | Read conversation, open obvious files (<=5), dispatch scouts.            |
| 2    | Deepen    | 1x   | Process scout results, verify by reading files, deepen through dialogue. |
| 3    | Summarize | 1x   | Synthesize findings into a concise handoff summary.                      |

All steps advance linearly. The phase boundary after step 3 gives the user a
natural point to review the summary and discuss next steps.

---

## Step Design

### Step 1: Gather

The Gather step combines what was previously three separate activities
(reading the conversation, orienting in the codebase, and dispatching scouts)
into a single `koan_complete_step` cycle. This avoids the latency and context
re-derivation overhead of artificially separating them.

The step has a **5-file budget** for initial exploration: project root listing,
orientation files (README.md, AGENTS.md, CLAUDE.md), and files the conversation
explicitly referenced. This is enough to write scout prompts that reference
actual function names and file paths rather than conversation labels.

No read-only permission gate -- the Gather step has full access to all intake
tools including `koan_request_scouts`.

### Step 2: Deepen

The Deepen step builds genuine understanding through iterative dialogue with
the user. It processes scout results, verifies findings by reading source files
directly, identifies gaps, and asks the user targeted questions -- then deepens
further as each answer reveals new dimensions.

Key properties:

- **Scout verification**: Scouts are good at exploration but their output should
  be confirmed. The Deepen step reads actual files to verify key scout findings
  that affect scope or story boundaries.
- **Iterative deepening**: Understanding deepens through multiple rounds of
  dialogue. Each answer may shift the picture of adjacent areas, revealing
  assumptions the agent was making without realizing it. Multiple rounds of
  questions are expected for any non-trivial task.
- **Impact classification**: Each unknown is classified as ASK (user input
  needed) or SAFE (implementation detail). Only ASK items become questions.
- **Default-ask framing**: Question-asking is the default; skipping requires
  triple justification. This inverts the typical LLM bias toward advancing.

### Step 3: Summarize

The Summarize step synthesizes findings into a concise summary covering: task
scope, key codebase findings, decisions made, constraints, and open items.
This summary lives in the LLM's context -- downstream phases (plan-spec,
plan-review) trust it as their starting point. See
[phase-trust.md](./phase-trust.md) for the trust model.

The Summarize step exists as a distinct step (rather than being folded into the
end of Deepen) for a structural reason: the RAG injection pipeline captures the
orchestrator's last prose turn before `koan_yield` at each phase boundary as
that phase's summary. Embedding the synthesis inside Deepen means subsequent
`koan_complete_step` calls could follow the synthesis text, displacing it as the
final captured turn and degrading the RAG anchor for the next phase. A dedicated
step ensures the synthesis is the last cognitive act before the phase boundary,
making the captured summary clean and unambiguous.

---

## Phase Boundary

After step 3 completes, `get_next_step()` returns `None`, which triggers the
phase boundary. The orchestrator presents suggested next phases with
descriptions, and asks the user what to do next.

```python
def get_next_step(step, ctx):
    if step < TOTAL_STEPS:
        return step + 1
    return None  # phase complete
```

---

## Prompt Engineering Principles

The intake prompts apply several techniques from the prompting literature.
This section records the reasoning so future changes don't inadvertently remove
mechanisms that address specific failure modes.

### MARP (Maximizing Operations per Step)

The three-step structure applies the MARP principle: maximize operations
per `koan_complete_step` call while minimizing planning or meta-reasoning
steps. Each step does real work across multiple activities rather than
artificially separating them into sequential tool calls. Gather combines
reading, orientation, and scout dispatch in a single step. Deepen combines
scout result processing, direct file verification, and iterative dialogue.
Summarize is a distinct step rather than being folded into Deepen because
it serves a structural role in the RAG injection pipeline (see
[Step 3: Summarize](#step-3-summarize) above).

### Iterative deepening through dialogue

The Deepen step positions dialogue as the core mechanism, not an afterthought.
The agent maps knowns and unknowns, then enters an iterative loop: ask
questions, process answers, verify against code, surface new gaps, and ask
again. Each answer is treated as a thread to pull -- it may shift understanding
of adjacent areas and reveal assumptions the agent was making without realizing
it. This ripple effect is what produces genuine understanding rather than
surface-level coverage.

### Default-ask question framing (preventing question avoidance)

The Deepen step frames question-asking as the default, with skipping
requiring triple justification. This inverts the typical LLM bias toward
advancing the workflow.

### Stakes framing (EmotionPrompt for accountability)

The system prompt includes: "A question you don't ask is an answer you're
making up." This connects intake shortcuts directly to downstream failures.

### Contrastive examples for thinking density

The system prompt includes WRONG → RIGHT examples for processing scout reports,
resolving conflicts, and classifying unknowns. These demonstrate the target
density for internal reasoning without affecting tool arguments or written
artifacts.

---

## Pitfalls

### Don't re-add a step-1 read-only gate for intake

Intake's Gather step needs all tools (especially `koan_request_scouts`) from
the start. The brief-generation phase still has a step-1 read-only gate, but intake
does not.

### Don't add a confidence loop

Previous iterations had a confidence-gated loop (steps 2-4 repeating).
This was removed because: (a) it produced unnecessary second scout batches,
(b) the self-verification step (Reflect) risked intrinsic self-correction
without external grounding, and (c) one focused pass is sufficient when the
Evaluate step is thorough.

### Don't separate scout verification from question-asking

Scout result evaluation and question formulation are tightly coupled -- a scout
finding directly informs what questions to ask. Separating them forces the LLM
to defer questions it could ask immediately.

### Don't cap question rounds

Previous iterations suggested "aim for 3-5 questions" in a single batch. This
created an implicit ceiling that discouraged iterative deepening. The current
design has no per-round limit and explicitly expects multiple rounds for
non-trivial tasks. Completion is defined by depth of understanding, not
question count.
