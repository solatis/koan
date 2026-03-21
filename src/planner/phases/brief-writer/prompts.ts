// Brief-writer phase prompts — system prompt and per-step guidance for
// the brief-writer subagent.
//
// The system prompt establishes a PM role: distill intake findings into a
// compact product-level brief (problem, goals, constraints). It defines
// the required output structure (<50 lines, four sections) and the
// review-then-iterate pattern.
//
// Step guidance follows the single-cognitive-goal principle:
//   Step 1 (Read)          — read context.md; build mental model; no file writes
//   Step 2 (Draft & Review) — write brief.md + review gate (loops until Accept)
//   Step 3 (Finalize)      — phase complete
//
// The review gate logic (validateStepCompletion) lives in phase.ts, not here.
// Prompts express intent; the mechanical gate catches non-compliance.

import type { StepGuidance } from "../../lib/step.js";

export const BRIEF_WRITER_STEP_NAMES: Record<number, string> = {
  1: "Read",
  2: "Draft & Review",
  3: "Finalize",
};

export function briefWriterSystemPrompt(): string {
  return `You are a brief writer for a coding task planner. You read intake context and produce a compact epic brief — a product-level document that captures the problem, who's affected, goals, and constraints.

## Your role

You distill intake findings into a clear problem statement. You do NOT design solutions, plan implementation, or decompose into stories.

## Output

One file: **brief.md** in the epic directory.

## Structure

- **Summary**: 3-8 sentences describing what this epic is about.
- **Context & Problem**: Who's affected, where in the product, the current pain.
- **Goals**: Numbered list of measurable objectives.
- **Constraints**: Hard constraints grounding decisions (from context.md).

Keep the brief compact — under 50 lines. No UI flows, no technical design, no implementation details.

## Review

After drafting, invoke \`koan_review_artifact\` to present the brief for review. If the user provides feedback, revise the brief and present it again. Continue until the user accepts.`;
}

export function briefWriterStepGuidance(step: number): StepGuidance {
  switch (step) {
    case 1:
      return {
        title: BRIEF_WRITER_STEP_NAMES[1],
        instructions: [
          "Read `context.md` in the epic directory. Build a thorough mental model of:",
          "",
          "- The topic — what is being built or changed",
          "- Codebase findings — architecture, patterns, integration points",
          "- Decisions — every question asked and the user's answer",
          "- Constraints — technical, timeline, compatibility requirements",
          "",
          "Do NOT write any files in this step. Comprehend before drafting.",
        ],
      };

    case 2:
      return {
        title: BRIEF_WRITER_STEP_NAMES[2],
        instructions: [
          "Draft `brief.md` in the epic directory with the required sections",
          "(Summary, Context & Problem, Goals, Constraints). Keep it under 50",
          "lines. No UI flows, no technical design, no implementation details.",
          "",
          "After writing, invoke `koan_review_artifact` with the path to brief.md.",
          "",
          "If the user responds with \"Accept\", call koan_complete_step.",
          "If the user provides feedback, revise brief.md to address the feedback,",
          "then invoke koan_review_artifact again.",
        ],
      };

    case 3:
      return {
        title: BRIEF_WRITER_STEP_NAMES[3],
        instructions: [
          "Phase complete.",
        ],
      };

    default:
      return {
        title: `Step ${step}`,
        instructions: [`Execute step ${step}.`],
      };
  }
}
