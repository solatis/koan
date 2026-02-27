import { promises as fs } from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

import type { ContextData } from "../../types.js";
import type { StepGuidance } from "../../lib/step.js";

export const STEP_NAMES: Record<1 | 2 | 3 | 4 | 5 | 6, string> = {
  1: "Extract Documentation Context",
  2: "Analyze Planned Code Changes",
  3: "Author Code-Adjacent Docs",
  4: "Author Cross-Cutting Docs",
  5: "Diagram & Consistency Review",
  6: "Validation & Final Review",
};

export async function loadPlanDocsSystemPrompt(): Promise<string> {
  const promptPath = path.join(os.homedir(), ".claude/agents/technical-writer.md");
  try {
    const content = await fs.readFile(promptPath, "utf8");
    return content.replace(/^---\n[\s\S]*?\n---\n/, "");
  } catch {
    throw new Error(`Technical-writer prompt not found at ${promptPath}`);
  }
}

export function formatContextForStep1(ctx: ContextData): string {
  return ["<planning_context>", JSON.stringify(ctx, null, 2), "</planning_context>"].join("\n");
}

export function buildPlanDocsSystemPrompt(basePrompt: string): string {
  return [
    basePrompt,
    "",
    "---",
    "",
    "WORKFLOW: 6-STEP PLAN-DOCS",
    "",
    "You are in planning mode. Add documentation artifacts to plan.json.",
    "Step 1 instructions are in the user message below.",
    "Complete each step, then call koan_complete_step.",
    "Put your findings in the `thoughts` parameter.",
    "The tool result contains the next step.",
    "",
    "CRITICAL:",
    "- NEVER use edit/write tools during plan-docs.",
    "- Populate code_change.doc_diff for code changes.",
    "- Keep comments and docs timeless (no temporal contamination).",
    "- Keep architecture diagrams and README entries aligned with plan intent.",
  ].join("\n");
}

export function planDocsStepGuidance(step: 1 | 2 | 3 | 4 | 5 | 6, context?: string): StepGuidance {
  switch (step) {
    case 1:
      return {
        title: "Step 1: Extract Documentation Context",
        instructions: [
          "PLANNING CONTEXT (from session):",
          "",
          context ?? "",
          "",
          "Use koan_get_plan to review decisions, constraints, risks, and milestones.",
          "Capture decision IDs that should be reflected in documentation rationale.",
          "This step is read-only.",
        ],
      };

    case 2:
      return {
        title: "Step 2: Analyze Planned Code Changes",
        instructions: [
          "Inspect each milestone and code_change:",
          "  - What needs doc_diff coverage?",
          "  - Which comments are missing or weak?",
          "  - Which changes require architecture/README support?",
          "",
          "Use koan_get_milestone / koan_get_change for detail.",
          "This step is read-only.",
        ],
      };

    case 3:
      return {
        title: "Step 3: Author Code-Adjacent Docs",
        instructions: [
          "Populate code-level documentation in plan.json:",
          "  - koan_set_change_doc_diff",
          "  - koan_set_change_comments",
          "",
          "Rules:",
          "  - Every code change with diff should have doc_diff",
          "  - comments explain WHY (reference decisions where applicable)",
          "  - Avoid temporal language (no 'added', 'changed from', 'now')",
        ],
      };

    case 4:
      return {
        title: "Step 4: Author Cross-Cutting Docs",
        instructions: [
          "Update cross-cutting documentation artifacts:",
          "  - koan_set_readme_entry for docs not tied to one change",
          "  - koan_set_diagram (title/scope/ascii_render) for architecture visuals",
          "",
          "If diagrams are missing but needed, create them with:",
          "  - koan_add_diagram",
          "  - koan_add_diagram_node / koan_add_diagram_edge",
        ],
      };

    case 5:
      return {
        title: "Step 5: Diagram & Consistency Review",
        instructions: [
          "Review documentation consistency across the plan:",
          "  - doc_diff content matches planned behavior",
          "  - diagrams align with milestone scope",
          "  - README entries do not contradict decisions/invariants",
          "",
          "Use getter tools to re-read affected entities and patch gaps.",
        ],
      };

    case 6:
      return {
        title: "Step 6: Validation & Final Review",
        instructions: [
          "Perform final documentation completeness check:",
          "  - all code changes with diff have doc_diff",
          "  - comments/doc diffs are coherent and timeless",
          "  - readme/diagram updates are present when needed",
          "",
          "Fix remaining issues before completing.",
        ],
        invokeAfter: [
          "WHEN DONE: Call koan_complete_step with a concise docs-completeness summary.",
          "Do NOT call this tool until documentation artifacts are complete.",
        ].join("\n"),
      };

    default:
      return { title: "", instructions: [] };
  }
}
