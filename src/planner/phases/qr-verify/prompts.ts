// Prompt guidance for the dynamic-step QR verify subagent workflow.
// Each reviewer subagent verifies 1..N QRItems (grouped by group_id).
//
// Dynamic step formula: totalSteps = 1 + (2 * numItems)
//   Step 1: CONTEXT (once, lists all items)
//   Steps 2..2N+1: ANALYZE/CONFIRM pairs per item

import type { QRItem } from "../../qr/types.js";
import { loadAgentPrompt } from "../../lib/agent-prompts.js";
import type { StepGuidance } from "../../lib/step.js";
import {
  buildPlanDesignContextTrigger,
  buildPlanDocsContextTrigger,
} from "../../lib/conversation-trigger.js";

type WorkPhaseKey = "plan-design" | "plan-code" | "plan-docs";

function scopeGuidance(item: QRItem): string {
  const s = item.scope;
  if (s === "*") {
    return "MACRO CHECK -- Use koan_get_plan to read the full plan.";
  }
  if (s.startsWith("milestone:")) {
    const milestoneId = s.slice("milestone:".length);
    return `MILESTONE CHECK -- Use koan_get_milestone(id='${milestoneId}') to read the milestone.`;
  }
  if (s.startsWith("code_intent:")) {
    const intentId = s.slice("code_intent:".length);
    return `CODE INTENT CHECK -- Use koan_get_intent(id='${intentId}') to read the intent.`;
  }
  if (s.startsWith("change:")) {
    const changeId = s.slice("change:".length);
    return `CHANGE CHECK -- Use koan_get_change(id='${changeId}') to read the planned change.`;
  }
  if (s.startsWith("decision:")) {
    const decisionId = s.slice("decision:".length);
    return `DECISION CHECK -- Use koan_get_decision(id='${decisionId}') to read the decision.`;
  }
  return "SCOPED CHECK -- Read the relevant section using plan getter tools.";
}

function phaseContextTrigger(
  phase: WorkPhaseKey,
  conversationPath?: string,
): string[] {
  if (phase === "plan-design") {
    return buildPlanDesignContextTrigger(conversationPath ?? "<planDir>/conversation.jsonl");
  }
  if (phase === "plan-docs") {
    return buildPlanDocsContextTrigger(conversationPath ?? "<planDir>/conversation.jsonl");
  }
  return [];
}

export async function loadQRVerifySystemPrompt(): Promise<string> {
  return loadAgentPrompt("quality-reviewer");
}

export function buildVerifySystemPrompt(basePrompt: string, phase: WorkPhaseKey, itemCount: number): string {
  const itemLabel = itemCount === 1 ? "1 QR item" : `${itemCount} QR items`;
  return [
    basePrompt,
    "",
    "---",
    "",
    `WORKFLOW: QR VERIFICATION (${phase}, ${itemLabel})`,
    "",
    `You will verify ${itemLabel} against the plan.`,
    "Step 1 instructions are in the user message below.",
    "Complete the work described, then call koan_complete_step.",
    "Put your findings in the `thoughts` parameter of koan_complete_step.",
    "",
    "CRITICAL: Do NOT record a verdict until the CONFIRM step for each item.",
    "Analyze thoroughly in the ANALYZE step before committing.",
  ].join("\n");
}

function formatItemForContext(item: QRItem): string {
  return [
    `  ${item.id} [${item.severity}]: ${item.check}`,
    `    scope: ${item.scope}`,
  ].join("\n");
}

export function buildContextStep(
  items: QRItem[],
  phase: WorkPhaseKey,
  conversationPath?: string,
): StepGuidance {
  const itemLabel = items.length === 1 ? "1 ITEM" : `${items.length} ITEMS`;
  const itemSummary = items.map(formatItemForContext).join("\n");

  return {
    title: `Step 1: CONTEXT`,
    instructions: [
      `PHASE: ${phase}`,
      `ITEMS TO VERIFY: ${itemLabel}`,
      "",
      itemSummary,
      "",
      ...phaseContextTrigger(phase, conversationPath),
      ...(phase === "plan-code" ? [] : [""]),
      "Understand the checks and required evidence before analyzing.",
    ],
  };
}

export function buildAnalyzeStep(item: QRItem, itemIndex: number, totalItems: number): StepGuidance {
  const positionLabel = totalItems === 1
    ? ""
    : ` (item ${itemIndex + 1} of ${totalItems})`;

  return {
    title: `ANALYZE ${item.id}${positionLabel}`,
    instructions: [
      scopeGuidance(item),
      "",
      "<qr_item_to_verify>",
      `  <id>${item.id}</id>`,
      `  <scope>${item.scope}</scope>`,
      `  <check>${item.check}</check>`,
      `  <severity>${item.severity}</severity>`,
      "</qr_item_to_verify>",
      "",
      "TASK:",
      "1. Read relevant entities based on scope",
      "2. Apply the verification check",
      "3. Form preliminary PASS/FAIL conclusion",
      "4. Gather concrete evidence",
      "",
      "Do NOT update QR state yet.",
    ],
  };
}

export function buildConfirmStep(
  item: QRItem,
  itemIndex: number,
  totalItems: number,
  phase: WorkPhaseKey,
): StepGuidance {
  const positionLabel = totalItems === 1
    ? ""
    : ` (item ${itemIndex + 1} of ${totalItems})`;

  return {
    title: `CONFIRM ${item.id}${positionLabel}`,
    instructions: [
      `CONFIRMING: ${item.id}`,
      `SEVERITY: ${item.severity}`,
      "",
      "CONFIDENCE CHECK:",
      "- Are you confident in your conclusion?",
      "- Is evidence specific and verifiable?",
      "",
      "RECORD RESULT:",
      "",
      "If PASS:",
      `  koan_qr_set_item(id='${item.id}', status='PASS')`,
      "",
      "If FAIL:",
      `  koan_qr_set_item(id='${item.id}', status='FAIL', finding='<one-line explanation>')`,
      "",
      "RULES:",
      "- FAIL requires finding",
      "- PASS must not include finding",
      "",
      "Execute ONE verdict call, then call koan_complete_step.",
    ],
    invokeAfter: [
      "WHEN DONE: Call koan_complete_step after recording your verdict.",
      "Do NOT call this tool until you have called koan_qr_set_item.",
    ].join("\n"),
  };
}
