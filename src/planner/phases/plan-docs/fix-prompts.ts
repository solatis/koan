import type { QRItem } from "../../qr/types.js";
import type { StepGuidance } from "../../lib/step.js";

export function formatFailuresXml(failures: ReadonlyArray<QRItem>): string {
  const items = failures
    .map((f) => [
      `  <item id="${f.id}" severity="${f.severity}" scope="${f.scope}">`,
      `    <check>${f.check}</check>`,
      f.finding ? `    <finding>${f.finding}</finding>` : "    <finding/>",
      "  </item>",
    ].join("\n"))
    .join("\n");
  return ["<qr_failures>", items, "</qr_failures>"].join("\n");
}

export function fixStepName(step: number, totalSteps: number, item?: QRItem): string {
  if (step === 1) return "Understand QR Failures";
  if (step === totalSteps) return "Review & Finalize";
  return item ? `Fix ${item.id}` : `Fix item ${step - 1}`;
}

export function buildFixSystemPrompt(basePrompt: string, failureCount: number, totalSteps: number): string {
  return [
    basePrompt,
    "",
    "---",
    "",
    `WORKFLOW: ${totalSteps}-STEP PLAN-DOCS FIX`,
    "",
    `You are fixing ${failureCount} documentation-related QR failure(s).`,
    "Step 1 is read-only and covers all failures.",
    `Steps 2-${totalSteps - 1} fix exactly one failure per step.`,
    `Step ${totalSteps} is read-only review.`,
    "",
    "CONSTRAINTS:",
    "- Fix only identified failures",
    "- Keep docs timeless and decision-grounded",
    "- Preserve already-valid doc artifacts",
  ].join("\n");
}

function step1(totalSteps: number, failuresXml: string): StepGuidance {
  const itemCount = totalSteps - 2;
  return {
    title: `Step 1/${totalSteps}: Understand QR Failures`,
    instructions: [
      "QR FAILURES:",
      "",
      failuresXml,
      "",
      `There are ${itemCount} item(s). You will fix them one by one in steps 2-${totalSteps - 1}.`,
      "Inspect current docs state via koan_get_plan / koan_get_change.",
      "Identify exact correction needed per item.",
      "",
      "This step is read-only.",
    ],
  };
}

function itemStep(step: number, totalSteps: number, item?: QRItem): StepGuidance {
  const itemXml = item ? formatFailuresXml([item]) : "<qr_failures/>";
  const idx = step - 1;
  const total = totalSteps - 2;
  return {
    title: `Step ${step}/${totalSteps}: Fix ${item?.id ?? `item ${idx}`}`,
    instructions: [
      `FIX ITEM ${idx} OF ${total}:`,
      "",
      itemXml,
      "",
      "Apply a targeted docs fix using doc tools (set doc_diff/comments/readme/diagram).",
      "Do not batch-fix other failures in this step.",
      "Keep changes minimal and scoped.",
    ],
  };
}

function finalStep(totalSteps: number): StepGuidance {
  return {
    title: `Step ${totalSteps}/${totalSteps}: Review & Finalize`,
    instructions: [
      "All per-item fixes are complete.",
      "Use koan_get_plan to verify docs coherence and completeness.",
      "Confirm fixed items are addressed without regressing passing items.",
      "",
      "This step is read-only.",
    ],
    invokeAfter: [
      "WHEN DONE: Call koan_get_plan, then call koan_complete_step.",
      "Do NOT call koan_complete_step before reviewing final plan state.",
    ].join("\n"),
  };
}

export function fixStepGuidance(
  step: number,
  totalSteps: number,
  opts?: { item?: QRItem; allFailuresXml?: string },
): StepGuidance {
  if (step === 1) return step1(totalSteps, opts?.allFailuresXml ?? "");
  if (step === totalSteps) return finalStep(totalSteps);
  return itemStep(step, totalSteps, opts?.item);
}
