// QR decompose phase prompts -- 13-step workflow for decomposing a plan into
// verifiable QR items. Follows the same structure as plan-design/prompts.ts.
// All tool calls reference phase='plan-design' explicitly so the decompose
// agent always writes to the correct QR namespace.

import { promises as fs } from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

import type { ContextData } from "../../types.js";
import type { StepGuidance } from "../../lib/step.js";

// -- Types --

export type DecomposeStep = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13;

// -- Constants --

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

// -- Exports --

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

export function buildDecomposeSystemPrompt(basePrompt: string): string {
  return [
    basePrompt,
    "",
    "---",
    "",
    "WORKFLOW: 13-STEP QR DECOMPOSITION (plan-design)",
    "",
    "You will execute a 13-step workflow to decompose a plan into verifiable QR items.",
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
  return [
    "<planning_context>",
    JSON.stringify(ctx, null, 2),
    "</planning_context>",
  ].join("\n");
}

export function decomposeStepGuidance(step: DecomposeStep, context?: string): StepGuidance {
  switch (step) {
    case 1:
      return {
        title: "Step 1: Absorb Context",
        instructions: [
          "PLANNING CONTEXT (from session):",
          "",
          context ?? "",
          "",
          "Use koan_get_plan to read the full plan.",
          "Absorb the plan structure: overview, constraints, milestones, decisions, code_intents, risks, invisible_knowledge.",
          "Identify the key entities and relationships that will need verification.",
        ],
      };

    case 2:
      return {
        title: "Step 2: Holistic Concerns",
        instructions: [
          "Identify plan-wide concerns that apply across all milestones.",
          "Consider: structural completeness, logical consistency, risk coverage, dependency ordering.",
          "Focus on plan-level quality -- not code correctness.",
          "These concerns become scope='*' items in later steps.",
        ],
      };

    case 3:
      return {
        title: "Step 3: Structural Enumeration",
        instructions: [
          "Enumerate every major entity in the plan:",
          "  - Decisions (DL-xxx)",
          "  - Constraints",
          "  - Risks",
          "  - Milestones (M-xxx) and their code_intents (CI-M-xxx-xxx)",
          "  - Invisible knowledge entries",
          "  - Waves and ordering",
          "Track counts for validation in step 8.",
        ],
      };

    case 4:
      return {
        title: "Step 4: Gap Analysis",
        instructions: [
          "Compare holistic concerns (step 2) against structural entities (step 3).",
          "Identify gaps: concerns not covered by any entity, entities lacking justification.",
          "Note areas where the plan is thin or under-specified.",
        ],
      };

    case 5:
      return {
        title: "Step 5: Generate Items",
        instructions: [
          "Generate QR items from the analysis in steps 2-4.",
          "Use koan_qr_add_item to create each item. Always pass phase='plan-design'.",
          "",
          "SCOPE VOCABULARY:",
          "  '*' -- plan-wide check",
          "  'milestone:M-001' -- milestone-specific check",
          "  'decision:DL-001' -- decision-specific check",
          "  'code_intent:CI-M-001-001' -- code intent-specific check",
          "",
          "SEVERITY:",
          "  MUST -- blocks all iterations (critical defect)",
          "  SHOULD -- important quality issue",
          "  COULD -- nice-to-have improvement",
          "",
          "Generate items covering: structural completeness, decision reasoning chains,",
          "risk coverage, milestone scoping, code intent clarity, constraint satisfaction.",
        ],
      };

    case 6:
      return {
        title: "Step 6: Atomicity Check",
        instructions: [
          "Review each generated item. Each item should test exactly one concern.",
          "If an item covers multiple concerns, split it:",
          "  Use koan_qr_add_item for each child item.",
          "  The original becomes the parent (parent_id on children).",
          "Atomic items are easier to verify independently.",
        ],
      };

    case 7:
      return {
        title: "Step 7: Coverage Validation",
        instructions: [
          "Cross-reference items against the plan structure.",
          "Every milestone should have at least one QR item.",
          "Every decision should have at least one QR item.",
          "High-severity risks should have corresponding QR items.",
          "Use koan_qr_add_item for any gaps found.",
        ],
      };

    case 8:
      return {
        title: "Step 8: Validate Items",
        instructions: [
          "Items are already on disk (each koan_qr_add_item wrote immediately).",
          "Use koan_qr_summary(phase='plan-design') to verify counts.",
          "Use koan_qr_list_items(phase='plan-design') to review all items.",
          "Check: no duplicate checks, severity levels appropriate, scopes valid.",
          "Add missing items with koan_qr_add_item if gaps found.",
        ],
      };

    case 9:
      return {
        title: "Step 9: Structural Grouping",
        instructions: [
          "Begin organizing items into review groups.",
          "DETERMINISTIC RULES:",
          "  - Parent-child items share the same group",
          "  - Umbrella items (scope='*') get group_id='umbrella'",
          "",
          "Use koan_qr_list_items(phase='plan-design') to see current items.",
          "Use koan_qr_assign_group(phase='plan-design', ids=[...], group_id='...') to assign groups.",
        ],
      };

    case 10:
      return {
        title: "Step 10: Component Grouping",
        instructions: [
          "Group remaining ungrouped items by plan component.",
          "Group candidates: a major milestone, a major decision, a constraint category.",
          "",
          "Use koan_qr_list_items(phase='plan-design') to see ungrouped items.",
          "Use koan_qr_assign_group(phase='plan-design', ids=[...], group_id='...') to assign.",
        ],
      };

    case 11:
      return {
        title: "Step 11: Concern Grouping",
        instructions: [
          "Group remaining ungrouped items by concern type.",
          "Group candidates: reasoning chain quality, reference integrity, risk coverage.",
          "",
          "Use koan_qr_list_items(phase='plan-design') to see ungrouped items.",
          "Use koan_qr_assign_group(phase='plan-design', ids=[...], group_id='...') to assign.",
        ],
      };

    case 12:
      return {
        title: "Step 12: Affinity Grouping",
        instructions: [
          "Assign remaining ungrouped items to groups based on similarity.",
          "Singletons are acceptable -- not every item needs a multi-member group.",
          "",
          "Use koan_qr_list_items(phase='plan-design') to see ungrouped items.",
          "Use koan_qr_assign_group(phase='plan-design', ids=[...], group_id='...') to assign.",
        ],
      };

    case 13:
      return {
        title: "Step 13: Final Validation",
        instructions: [
          "Validate all items are grouped and well-formed.",
          "Use koan_qr_summary(phase='plan-design') to check final counts.",
          "Use koan_qr_list_items(phase='plan-design') to verify all items have group_id.",
          "If any items lack group_id, assign them now.",
          "Output 'PASS' in thoughts if all items are valid and grouped.",
        ],
        invokeAfter: [
          "WHEN DONE: Call koan_complete_step with 'PASS' or issues found in the `thoughts` parameter.",
          "Do NOT call this tool until validation is complete.",
        ].join("\n"),
      };

    default:
      return { title: "", instructions: [] };
  }
}
