// koan_set_confidence tool -- intake phase confidence gate.
//
// Called by the intake agent during the Reflect step (step 4) to declare its
// current confidence that sufficient context has been gathered for the
// decomposer to split the work into stories.
//
// The IntakePhase reads intakeState.confidence in getNextStep() to decide
// whether to loop back to Scout (step 2) or advance to Synthesize (step 5).
// Confidence is reset to null at every loop-back, so each Reflect step
// requires a fresh assessment -- carry-over from a previous iteration is
// not possible.
//
// Confidence changes are appended to events.jsonl via the EventLog. The
// web server polls state.json (the folded projection) and can push SSE events
// to the UI when the intakeConfidence or intakeIteration fields change.

import { Type } from "@sinclair/typebox";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import type { EventLog } from "../lib/audit.js";
import type { ConfidenceRef } from "../phases/intake/phase.js";

// All valid confidence levels, ordered from least to most confident.
export type ConfidenceLevel = "exploring" | "low" | "medium" | "high" | "certain";

// Narrow audit dependency for the confidence tool. Kept separate from
// ConfidenceRef so that confidence state and event logging are independent
// concerns. Any object with a nullable eventLog field satisfies this --
// RuntimeContext does at the call site.
export interface AuditRef {
  readonly eventLog: EventLog | null;
}

const CONFIDENCE_TOOL_DESCRIPTION = `
Declare your current confidence that you have gathered sufficient context for the decomposer to split the work into stories.

Call this BEFORE koan_complete_step during the Reflect step. Required -- step completion will be rejected without it.

Levels (from lowest to highest):
- exploring: Just started. Have not yet scouted or asked questions.
- low: Major gaps. Cannot define story boundaries.
- medium: Broad shape understood, specific boundaries unclear.
- high: Scope, boundaries, key decisions understood. Minor unknowns remain that would not change story structure.
- certain: Decomposer has everything it needs. No question would change story boundaries.
`.trim();

// ConfidenceRef provides confidence state (iteration + setConfidence).
// AuditRef provides event logging separately, keeping the two concerns
// decoupled. Both are stable mutable refs satisfying the pi lifecycle
// constraint that tools register before before_agent_start.
export function registerConfidenceTool(pi: ExtensionAPI, confidenceRef: ConfidenceRef, auditRef: AuditRef): void {
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

      // Store on IntakeState so IntakePhase.getNextStep() can read it at step completion.
      confidenceRef.setConfidence(level);

      // Emit a confidence_change audit event. The EventLog folds it into
      // state.json (updating intakeConfidence and intakeIteration fields),
      // which the web server polls to push SSE events to the UI.
      if (auditRef.eventLog) {
        await auditRef.eventLog.emitConfidenceChange(level, confidenceRef.iteration);
      }

      return {
        content: [{ type: "text" as const, text: `Confidence set to ${level}.` }],
        details: undefined,
      };
    },
  });
}
