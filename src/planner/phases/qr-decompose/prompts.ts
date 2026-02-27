// QR decompose phase prompts -- 13-step workflow for decomposing a plan into
// verifiable QR items. Prompt text is shared across plan-design, plan-code,
// and plan-docs via the injected phase key.

import { promises as fs } from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

import type { ContextData } from "../../types.js";
import type { StepGuidance } from "../../lib/step.js";

export type DecomposeStep = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13;
export type WorkPhaseKey = "plan-design" | "plan-code" | "plan-docs";

export const DECOMPOSE_STEP_NAMES: Record<DecomposeStep, string> = {
  1: "Absorb Context",
  2: "Holistic Concerns",
  3: "Structural Enumeration",
  4: "Gap Analysis",
  5: "Generate Items",
  6: "Atomicity Check",
  7: "Coverage Validation",
  8: "Validate Items",
  9: "Structural Grouping",
  10: "Component Grouping",
  11: "Concern Grouping",
  12: "Affinity Grouping",
  13: "Final Validation",
};

const PHASE_SCOPE_HINTS: Record<WorkPhaseKey, string[]> = {
  "plan-design": [
    "decision:DL-001 -- decision reasoning quality",
    "milestone:M-001 -- milestone structure",
    "code_intent:CI-M-001-001 -- intent clarity",
  ],
  "plan-code": [
    "milestone:M-001 -- code change coverage",
    "code_intent:CI-M-001-001 -- intent->change linkage",
    "change:CC-M-001-001 -- diff quality/anchor correctness",
  ],
  "plan-docs": [
    "milestone:M-001 -- docs completeness",
    "change:CC-M-001-001 -- doc_diff/comments quality",
    "diagram:DIAG-001 -- architecture docs fidelity",
  ],
};

export async function loadQRDecomposeSystemPrompt(): Promise<string> {
  const homeDir = os.homedir();
  const promptPath = path.join(homeDir, ".claude/agents/quality-reviewer.md");
  try {
    const content = await fs.readFile(promptPath, "utf8");
    const body = content.replace(/^---\n[\s\S]*?\n---\n/, "");
    return body;
  } catch {
    throw new Error(`Quality reviewer prompt not found at ${promptPath}`);
  }
}

export function buildDecomposeSystemPrompt(basePrompt: string, phase: WorkPhaseKey): string {
  return [
    basePrompt,
    "",
    "---",
    "",
    `WORKFLOW: 13-STEP QR DECOMPOSITION (${phase})`,
    "",
    "You will execute a 13-step workflow to decompose the current plan phase into verifiable QR items.",
    "Step 1 instructions are in the user message below.",
    "Complete the work described, then call koan_complete_step.",
    "Put your findings in the `thoughts` parameter of koan_complete_step.",
    "The tool result contains the next step's instructions.",
    "",
    "CRITICAL: Do the actual work described in each step BEFORE calling",
    "koan_complete_step. Read the plan, analyze, generate items. Do not skip.",
  ].join("\n");
}

export function formatContextForDecompose(ctx: ContextData): string {
  return ["<planning_context>", JSON.stringify(ctx, null, 2), "</planning_context>"].join("\n");
}

export function decomposeStepGuidance(step: DecomposeStep, phase: WorkPhaseKey, context?: string): StepGuidance {
  switch (step) {
    case 1:
      return {
        title: "Step 1: Absorb Context",
        instructions: [
          `PHASE: ${phase}`,
          "PLANNING CONTEXT (from session):",
          "",
          context ?? "",
          "",
          "Use koan_get_plan to read the full plan.",
          "Absorb the structures relevant to this phase and identify what needs verification.",
        ],
      };

    case 2:
      return {
        title: "Step 2: Holistic Concerns",
        instructions: [
          `List phase-wide concerns for ${phase}.`,
          "Focus on quality/completeness/consistency concerns, not implementation details.",
          "These become umbrella items (scope='*').",
        ],
      };

    case 3:
      return {
        title: "Step 3: Structural Enumeration",
        instructions: [
          `Enumerate concrete entities touched by ${phase}.`,
          "Track IDs and counts so step 7 can validate coverage.",
          "Use getter tools to resolve uncertain IDs.",
        ],
      };

    case 4:
      return {
        title: "Step 4: Gap Analysis",
        instructions: [
          "Map concerns (step 2) to entities (step 3).",
          "Identify uncovered concerns and under-specified entities.",
        ],
      };

    case 5:
      return {
        title: "Step 5: Generate Items",
        instructions: [
          "Generate QR items with koan_qr_add_item.",
          `Always pass phase='${phase}'.`,
          "",
          "Scope examples for this phase:",
          ...PHASE_SCOPE_HINTS[phase].map((hint) => `  - ${hint}`),
          "",
          "Severity:",
          "  MUST -- critical defect",
          "  SHOULD -- significant quality issue",
          "  COULD -- non-blocking improvement",
        ],
      };

    case 6:
      return {
        title: "Step 6: Atomicity Check",
        instructions: [
          "Ensure each item checks exactly one concern.",
          "Split non-atomic items by adding child items when needed.",
        ],
      };

    case 7:
      return {
        title: "Step 7: Coverage Validation",
        instructions: [
          "Cross-check item set against structural enumeration from step 3.",
          "Add missing items for uncovered entities/concerns.",
        ],
      };

    case 8:
      return {
        title: "Step 8: Validate Items",
        instructions: [
          "Use koan_qr_summary and koan_qr_list_items to audit generated items.",
          `Always pass phase='${phase}'.`,
          "Fix duplicates or malformed scopes by adding/revising items.",
        ],
      };

    case 9:
      return {
        title: "Step 9: Structural Grouping",
        instructions: [
          "Assign deterministic groups:",
          "  - Parent/child items share group",
          "  - Umbrella items (scope='*') use group_id='umbrella'",
          `Use koan_qr_assign_group(phase='${phase}', ...)`,
        ],
      };

    case 10:
      return {
        title: "Step 10: Component Grouping",
        instructions: [
          "Group remaining ungrouped items by component (milestone/decision/change cluster).",
          `Use koan_qr_list_items(phase='${phase}') and koan_qr_assign_group(...)`,
        ],
      };

    case 11:
      return {
        title: "Step 11: Concern Grouping",
        instructions: [
          "Group remaining ungrouped items by concern type.",
          "Example concern groups: coverage, consistency, traceability, docs quality.",
        ],
      };

    case 12:
      return {
        title: "Step 12: Affinity Grouping",
        instructions: [
          "Assign any remaining ungrouped items by semantic affinity.",
          "Singleton groups are acceptable.",
        ],
      };

    case 13:
      return {
        title: "Step 13: Final Validation",
        instructions: [
          "Validate that all items are grouped and well-formed.",
          `Use koan_qr_summary(phase='${phase}') and koan_qr_list_items(phase='${phase}')`,
          "Ensure no item has null group_id.",
          "Output PASS in thoughts when complete.",
        ],
        invokeAfter: [
          "WHEN DONE: Call koan_complete_step with PASS or issues in `thoughts`.",
          "Do NOT call this tool until validation is complete.",
        ].join("\n"),
      };

    default:
      return { title: "", instructions: [] };
  }
}
