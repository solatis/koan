// koan_set_confidence tool — intake phase confidence gate.
//
// Called by the intake agent during the Reflect step (step 4) to declare its
// current confidence that sufficient context has been gathered for the
// decomposer to split the work into stories.
//
// The IntakePhase reads ctx.intakeConfidence in getNextStep() to decide
// whether to loop back to Scout (step 2) or advance to Synthesize (step 5).
// Confidence is reset to null at every loop-back, so each Reflect step
// requires a fresh assessment — carry-over from a previous iteration is
// not possible.
//
// Confidence changes are appended to events.jsonl via the EventLog. The
// web server polls state.json (the folded projection) and can push SSE events
// to the UI when the intakeConfidence or intakeIteration fields change.

import { Type } from "@sinclair/typebox";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import type { RuntimeContext } from "../lib/runtime-context.js";

// All valid confidence levels, ordered from least to most confident.
export type ConfidenceLevel = "exploring" | "low" | "medium" | "high" | "certain";

const CONFIDENCE_TOOL_DESCRIPTION = `
Declare your current confidence that you have gathered sufficient context for the decomposer to split the work into stories.

Call this BEFORE koan_complete_step during the Reflect step. Required — step completion will be rejected without it.

Levels (from lowest to highest):
- exploring: Just started. Have not yet scouted or asked questions.
- low: Major gaps. Cannot define story boundaries.
- medium: Broad shape understood, specific boundaries unclear.
- high: Scope, boundaries, key decisions understood. Minor unknowns remain that would not change story structure.
- certain: Decomposer has everything it needs. No question would change story boundaries.
`.trim();

export function registerConfidenceTool(pi: ExtensionAPI, ctx: RuntimeContext): void {
  pi.registerTool({
    name: "koan_set_confidence",
    label: "Set intake confidence",
    description: CONFIDENCE_TOOL_DESCRIPTION,
    parameters: Type.Object({
      level: Type.Union(
        [
          Type.Literal("exploring"),
          Type.Literal("low"),
          Type.Literal("medium"),
          Type.Literal("high"),
          Type.Literal("certain"),
        ],
        { description: "Your current confidence level (exploring | low | medium | high | certain)" },
      ),
    }),
    async execute(_toolCallId, params) {
      const { level } = params as { level: ConfidenceLevel };

      // Store on context so IntakePhase.getNextStep() can read it at step completion.
      ctx.intakeConfidence = level;

      // Emit a confidence_change audit event. The EventLog folds it into
      // state.json (updating intakeConfidence and intakeIteration fields),
      // which the web server polls to push SSE events to the UI.
      if (ctx.eventLog) {
        // ctx.intakeIteration is set by IntakePhase.onStepUpdated() when each step
        // is entered, so it always reflects the current iteration at tool call time.
        await ctx.eventLog.emitConfidenceChange(level, ctx.intakeIteration);
      }

      return {
        content: [{ type: "text" as const, text: `Confidence set to ${level}.` }],
        details: undefined,
      };
    },
  });
}
