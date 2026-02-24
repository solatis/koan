// Prompt guidance for the 3-step QR verify subagent workflow.
//
// Each reviewer subagent verifies exactly 1 QRItem against the plan.
// Steps: CONTEXT (understand the check) -> ANALYZE (read plan, apply check)
// -> CONFIRM (record verdict via koan_qr_set_item).

import { promises as fs } from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

import type { ContextData } from "../../types.js";
import type { QRItem } from "../../qr/types.js";
import type { StepGuidance } from "../../lib/step.js";

// -- Types --

export type VerifyStep = 1 | 2 | 3;

// -- Helpers --

function formatContextXml(ctx: ContextData): string {
  const fields = Object.entries(ctx)
    .map(([key, values]) => {
      const items = (values as string[]).map((v) => `    <item>${v}</item>`).join("\n");
      return `  <${key}>\n${items}\n  </${key}>`;
    })
    .join("\n");
  return `<planning_context>\n${fields}\n</planning_context>`;
}

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
  if (s.startsWith("decision:")) {
    const decisionId = s.slice("decision:".length);
    return `DECISION CHECK -- Use koan_get_decision(id='${decisionId}') to read the decision.`;
  }
  return "SCOPED CHECK -- Read the relevant section using plan getter tools.";
}

// -- Exports --

export async function loadQRVerifySystemPrompt(): Promise<string> {
  const promptPath = path.join(os.homedir(), ".claude/agents/quality-reviewer.md");
  try {
    const content = await fs.readFile(promptPath, "utf8");
    return content.replace(/^---\n[\s\S]*?\n---\n/, "");
  } catch {
    throw new Error(`Quality-reviewer prompt not found at ${promptPath}`);
  }
}

export function buildVerifySystemPrompt(basePrompt: string): string {
  return [
    basePrompt,
    "",
    "---",
    "",
    "WORKFLOW: 3-STEP QR VERIFICATION (plan-design)",
    "",
    "You will verify exactly 1 QR item against the plan.",
    "Step 1 instructions are in the user message below.",
    "Complete the work described, then call koan_complete_step.",
    "Put your findings in the `thoughts` parameter of koan_complete_step.",
    "",
    "CRITICAL: Do NOT record a verdict until step 3 (CONFIRM).",
    "Analyze thoroughly in step 2 before committing.",
  ].join("\n");
}

export function buildContextStep(item: QRItem, contextData: ContextData): StepGuidance {
  return {
    title: "Step 1: CONTEXT",
    instructions: [
      "PHASE: plan-design",
      "ITEM TO VERIFY:",
      "",
      "<qr_item_to_verify>",
      `  <id>${item.id}</id>`,
      `  <scope>${item.scope}</scope>`,
      `  <check>${item.check}</check>`,
      `  <severity>${item.severity}</severity>`,
      "</qr_item_to_verify>",
      "",
      "PLANNING CONTEXT (reference for semantic validation):",
      formatContextXml(contextData),
      "",
      "UNDERSTAND the check you need to perform.",
      "Note the scope: '*' means plan-wide check, 'milestone:X' means specific milestone.",
      "Severity indicates blocking behavior: MUST blocks all iterations.",
    ],
  };
}

export function buildAnalyzeStep(item: QRItem): StepGuidance {
  return {
    title: "Step 2: ANALYZE",
    instructions: [
      scopeGuidance(item),
      "",
      "TASK:",
      "1. Read relevant files/sections based on scope",
      "2. Apply the verification check",
      "3. Form preliminary conclusion: PASS or FAIL?",
      "4. If FAIL, note specific evidence",
      "",
      "DO NOT update QR state yet. Proceed to CONFIRM step.",
    ],
  };
}

export function buildConfirmStep(item: QRItem): StepGuidance {
  return {
    title: "Step 3: CONFIRM",
    instructions: [
      `CONFIRMING: ${item.id}`,
      `SEVERITY: ${item.severity}`,
      "",
      "CONFIDENCE CHECK:",
      "- Are you confident in your conclusion?",
      "- Did you verify against actual plan content?",
      "- Is your evidence specific and verifiable?",
      "",
      "RECORD RESULT:",
      "",
      "If PASS:",
      `  koan_qr_set_item(phase='plan-design', id='${item.id}', status='PASS')`,
      "",
      "If FAIL:",
      `  koan_qr_set_item(phase='plan-design', id='${item.id}', status='FAIL',`,
      "                    finding='<one-line explanation>')",
      "",
      "RULES:",
      "- FAIL requires finding (explains what failed)",
      "- PASS forbids finding (finding field must not be set)",
      "",
      "Execute ONE of the above tool calls, then call koan_complete_step.",
    ],
    invokeAfter: [
      "WHEN DONE: Call koan_complete_step after recording your verdict.",
      "Do NOT call this tool until you have called koan_qr_set_item.",
    ].join("\n"),
  };
}
