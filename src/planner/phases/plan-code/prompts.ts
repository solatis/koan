import { promises as fs } from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

import type { ContextData } from "../../types.js";
import type { StepGuidance } from "../../lib/step.js";

export const STEP_NAMES: Record<1 | 2 | 3 | 4, string> = {
  1: "Intent Coverage Analysis",
  2: "Codebase Anchoring",
  3: "Diff Authoring",
  4: "Validation & Review",
};

export async function loadPlanCodeSystemPrompt(): Promise<string> {
  const promptPath = path.join(os.homedir(), ".claude/agents/developer.md");
  try {
    const content = await fs.readFile(promptPath, "utf8");
    return content.replace(/^---\n[\s\S]*?\n---\n/, "");
  } catch {
    throw new Error(`Developer prompt not found at ${promptPath}`);
  }
}

export function formatContextForStep1(ctx: ContextData): string {
  return ["<planning_context>", JSON.stringify(ctx, null, 2), "</planning_context>"].join("\n");
}

export function buildPlanCodeSystemPrompt(basePrompt: string): string {
  return [
    basePrompt,
    "",
    "---",
    "",
    "WORKFLOW: 4-STEP PLAN-CODE",
    "",
    "You are in planning mode. Produce code diffs in plan.json, not repo edits.",
    "Step 1 instructions are in the user message below.",
    "Complete each step, then call koan_complete_step.",
    "Put your work output in the `thoughts` parameter.",
    "The tool result contains the next step.",
    "",
    "CRITICAL:",
    "- NEVER use edit/write tools during plan-code.",
    "- Convert every code_intent into at least one code_change with intent_ref.",
    "- Use unified diffs in code_change.diff.",
  ].join("\n");
}

export function planCodeStepGuidance(step: 1 | 2 | 3 | 4, context?: string): StepGuidance {
  switch (step) {
    case 1:
      return {
        title: "Step 1: Intent Coverage Analysis",
        instructions: [
          "PLANNING CONTEXT (from session):",
          "",
          context ?? "",
          "",
          "Use koan_get_plan to inspect milestones and code_intents.",
          "Build a checklist of intents that need code_changes.",
          "Record target files and affected functions per intent.",
          "",
          "This step is read-only.",
        ],
      };

    case 2:
      return {
        title: "Step 2: Codebase Anchoring",
        instructions: [
          "Read target files to anchor each planned diff:",
          "  - Use read/grep/find/bash as needed",
          "  - Identify stable context lines around each change",
          "  - Confirm naming/pattern conventions",
          "",
          "Do not create code_changes yet. This step is still read-only.",
        ],
      };

    case 3:
      return {
        title: "Step 3: Diff Authoring",
        instructions: [
          "Create code_changes for each intent using plan mutation tools:",
          "  - koan_add_change (if missing)",
          "  - koan_set_change_intent_ref",
          "  - koan_set_change_file",
          "  - koan_set_change_diff",
          "  - koan_set_change_comments",
          "",
          "Rules:",
          "  - Every code_intent must map to at least one code_change",
          "  - Use valid unified diff format in diff field",
          "  - comments explain WHY (reference decision IDs where relevant)",
          "",
          "Use koan_get_plan/koan_get_milestone to verify coverage as you go.",
        ],
      };

    case 4:
      return {
        title: "Step 4: Validation & Review",
        instructions: [
          "Run a final coverage review using getter tools:",
          "  - Every intent has at least one linked change",
          "  - Every change has exact file path and non-empty diff",
          "  - Diffs and comments are coherent with intent behavior",
          "",
          "Fix any gaps before completing this step.",
        ],
        invokeAfter: [
          "WHEN DONE: Call koan_complete_step with a concise summary of coverage.",
          "Do NOT call this tool until all required code_changes are present.",
        ].join("\n"),
      };

    default:
      return { title: "", instructions: [] };
  }
}
