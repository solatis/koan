// Fix-phase step guidance for plan-design targeted repair (3 steps).
//
// Parallels prompts.ts structure. Step 1 explicitly prohibits mutations:
// without this constraint the LLM tends to apply the first fix it identifies
// without reading all failures, producing cascading corrections that address
// symptoms rather than root causes.

import type { QRItem } from "../../qr/types.js";
import type { StepGuidance } from "../../lib/step.js";

export type FixStep = 1 | 2 | 3;

export const FIX_STEP_NAMES: Record<FixStep, string> = {
  1: "Understand QR Failures",
  2: "Apply Targeted Fixes",
  3: "Review & Finalize",
};

// Serializes FAIL items as an XML block injected into the step 1 prompt.
// XML structure mirrors how pi-native tools present structured data.
export function formatFailuresXml(failures: ReadonlyArray<QRItem>): string {
  const items = failures.map((f) => [
    `  <item id="${f.id}" severity="${f.severity}" scope="${f.scope}">`,
    `    <check>${f.check}</check>`,
    f.finding ? `    <finding>${f.finding}</finding>` : `    <finding/>`,
    `  </item>`,
  ].join("\n")).join("\n");

  return [
    "<qr_failures>",
    items,
    "</qr_failures>",
  ].join("\n");
}

// Appends fix workflow instructions to the base architect system prompt.
export function buildFixSystemPrompt(basePrompt: string, failureCount: number): string {
  return [
    basePrompt,
    "",
    "---",
    "",
    "WORKFLOW: 3-STEP PLAN-DESIGN FIX",
    "",
    `You are fixing ${failureCount} QR failure(s) in an existing plan.`,
    "Step 1 instructions are in the user message below.",
    "Complete the work described, then call koan_complete_step.",
    "Put your findings in the `thoughts` parameter of koan_complete_step.",
    "The tool result contains the next step's instructions.",
    "",
    "CRITICAL: Fix ONLY the identified failures. Do not restructure the plan",
    "beyond what the failures require. Prefer updating existing entities over",
    "adding new ones.",
  ].join("\n");
}

export function fixStepGuidance(step: FixStep, context?: string): StepGuidance {
  switch (step) {
    case 1:
      return {
        title: "Step 1: Understand QR Failures",
        instructions: [
          "QR FAILURES TO FIX:",
          "",
          context ?? "",
          "",
          "Read the failures carefully. For each failing item:",
          "  - Identify the scope (which milestone, decision, or intent)",
          "  - Understand what the check requires",
          "  - Read the finding to understand why it failed",
          "",
          "Use getter tools to inspect the scoped entities:",
          "  - koan_get_plan: overview, structure, decisions",
          "  - koan_get_milestone: milestone details and intents",
          "  - koan_get_decision: decision rationale",
          "  - koan_get_intent: intent definition",
          "",
          "Plan your fixes mentally. Consider:",
          "  - What minimal change addresses each failure?",
          "  - Do any fixes overlap or interact?",
          "  - Could fixing one item cause another to fail?",
          "",
          "DO NOT write any changes yet. Gather understanding for step 2.",
        ],
      };

    case 2:
      return {
        title: "Step 2: Apply Targeted Fixes",
        instructions: [
          "Apply the fixes you planned in step 1.",
          "",
          "Use plan mutation tools to address each failure:",
          "  - koan_set_overview / koan_set_constraints / koan_set_invisible_knowledge",
          "  - koan_set_milestone_* / koan_set_intent / koan_set_decision",
          "  - koan_add_milestone / koan_add_intent / koan_add_decision (if new entities needed)",
          "",
          "RULES:",
          "  - Fix ONLY the FAIL items from step 1",
          "  - Prefer updating existing entities over adding new ones",
          "  - Do not restructure the plan beyond what the failures require",
          "  - Do not change PASS items",
          "",
          "After applying all fixes, call koan_complete_step.",
        ],
      };

    case 3:
      return {
        title: "Step 3: Review & Finalize",
        instructions: [
          "Review the fixes you applied.",
          "",
          "Call koan_get_plan to read the current plan state.",
          "For each original failure, verify:",
          "  - The fix addresses the check that failed",
          "  - No regressions introduced in previously passing items",
          "  - The plan is internally consistent",
          "",
          "Summarize in the `thoughts` parameter of koan_complete_step:",
          "  - Which failures were fixed and how",
          "  - Any concerns or items that may still be at risk",
        ],
        // Step 3 requires reading the plan before completing -- the review
        // is meaningless without it. The custom invokeAfter enforces this
        // sequencing explicitly.
        invokeAfter: [
          "WHEN DONE: First call koan_get_plan to confirm the final plan state.",
          "Then call koan_complete_step with your review summary in the `thoughts` parameter.",
          "Do NOT call koan_complete_step before calling koan_get_plan.",
        ].join("\n"),
      };

    default:
      throw new Error(`unexpected fix step: ${step as never}`);
  }
}
