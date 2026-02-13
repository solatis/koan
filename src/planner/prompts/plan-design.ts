import { promises as fs } from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

import type { ContextData } from "../types.js";
import type { StepGuidance } from "./step.js";

export const STEP_NAMES: Record<1 | 2 | 3 | 4 | 5 | 6, string> = {
  1: "Task Analysis & Exploration Planning",
  2: "Codebase Exploration",
  3: "Testing Strategy Discovery",
  4: "Approach Generation",
  5: "Assumption Surfacing",
  6: "Milestone Definition & Plan Writing",
};

export async function loadPlanDesignSystemPrompt(): Promise<string> {
  const homeDir = os.homedir();
  const promptPath = path.join(homeDir, ".claude/agents/architect.md");
  try {
    const content = await fs.readFile(promptPath, "utf8");
    const body = content.replace(/^---\n[\s\S]*?\n---\n/, "");
    return body;
  } catch (error) {
    throw new Error(`Architect prompt not found at ${promptPath}`);
  }
}

export function formatContextForStep1(ctx: ContextData): string {
  return [
    "<planning_context>",
    JSON.stringify(ctx, null, 2),
    "</planning_context>",
  ].join("\n");
}

export function buildPlanDesignSystemPrompt(basePrompt: string): string {
  return [
    basePrompt,
    "",
    "---",
    "",
    "WORKFLOW: 6-STEP PLAN-DESIGN",
    "",
    "You will execute a 6-step workflow.",
    "Step 1 instructions are in the user message below.",
    "Complete the work described, then call koan_next_step.",
    "The tool result contains the next step's instructions.",
    "In step 6, use plan mutation tools, then call koan_next_step.",
    "",
    // Directive prevents immediate tool call without substantive work.
    // Failure mode: koan_next_step called with zero file reads,
    // producing an empty step with no exploration data. The directive
    // repeats guidance from tool descriptions to strengthen the signal.
    "CRITICAL: Do the actual work described in each step BEFORE calling",
    "koan_next_step. Read files, explore code, analyze. Do not skip.",
    "Do NOT produce a final text response until koan_next_step completes.",
  ].join("\n");
}

export function planDesignStepGuidance(step: 1 | 2 | 3 | 4 | 5 | 6, context?: string): StepGuidance {
  switch (step) {
    case 1:
      return {
        title: "Step 1: Task Analysis & Exploration Planning",
        instructions: [
          "PLANNING CONTEXT (from session):",
          "",
          context ?? "",
          "",
          "Parse the user's task description. Identify:",
          "  - What needs to change (files, modules, behavior)",
          "  - What exploration is needed (patterns, constraints, existing code)",
          "  - What directories/files are relevant",
          "",
          "Read project context files to understand structure:",
          "  - Project root CLAUDE.md",
          "  - Subdirectory CLAUDE.md files in relevant areas",
          "  - All paths in context.json reference_docs field (if any)",
          "",
          "CONTEXT.JSON CONTRACT: READ-ONLY.",
          "  - context.json is owned by the session",
          "  - You MUST NOT write, modify, or append to context.json",
          "  - Your outputs go to plan.json (step 6) -- never context.json",
          "",
          "DO NOT write any files yet. Gather understanding for step 2.",
          "Record your analysis mentally for use in subsequent steps.",
        ],
      };

    case 2:
      return {
        title: "Step 2: Codebase Exploration",
        instructions: [
          "Use Glob, Grep, Read tools directly to discover:",
          "  - Existing patterns and implementations",
          "  - Constraints from code structure",
          "  - Conventions to follow",
          "",
          "Read conventions/ files as needed:",
          "  - structural.md (architectural patterns)",
          "  - temporal.md (comment hygiene)",
          "  - diff-format.md (diff specification)",
          "",
          "NUDGE: If you need additional context to plan well, read more files.",
          "Better to over-explore than under-explore.",
          "",
          "Record discoveries for use in steps 4-6. Do NOT write files.",
        ],
      };

    case 3:
      return {
        title: "Step 3: Testing Strategy Discovery",
        instructions: [
          "DISCOVER testing strategy from:",
          "  - User conversation hints",
          "  - Project CLAUDE.md / README.md",
          "  - conventions/structural.md domain='testing-strategy'",
          "",
          "Record confirmed strategy for use in step 6.",
          "Decisions will be recorded via tools in step 6.",
        ],
      };

    case 4:
      return {
        title: "Step 4: Approach Generation",
        instructions: [
          "GENERATE 2-3 approach options:",
          "  - Include 'minimal change' option",
          "  - Include 'idiomatic/modern' option",
          "  - Document advantage/disadvantage for each",
          "",
          "TARGET TECH RESEARCH (if new tech/migration):",
          "  - What is canonical usage of target tech?",
          "  - Does it have different abstractions?",
          "",
          "Use exploration findings from step 2 to ground tradeoffs.",
          "Record approach analysis for step 6.",
        ],
      };

    case 5:
      return {
        title: "Step 5: Assumption Surfacing",
        instructions: [
          "FAST PATH: Skip if task involves NONE of:",
          "  - Migration to new tech",
          "  - Policy defaults (lifecycle, capacity, failure handling)",
          "  - Architectural decisions with multiple valid approaches",
          "",
          "FULL CHECK (if any apply):",
          "  Audit each category with OPEN questions:",
          "    Pattern preservation, Migration strategy, Idiomatic usage,",
          "    Abstraction boundary, Policy defaults",
          "",
          "Record assumptions for step 6.",
        ],
      };

    case 6:
      return {
        title: "Step 6: Milestone Definition & Plan Writing",
        instructions: [
          "EVALUATE approaches: P(success), failure mode, backtrack cost",
          "",
          "SELECT and record in Decision Log with MULTI-STEP chain:",
          "  BAD:  'Polling | Webhooks unreliable'",
          "  GOOD: 'Use polling | 30% webhook failure -> need fallback anyway -> polling simpler'",
          "",
          "Use the following tools to build the plan:",
          "",
          "OVERVIEW & CONSTRAINTS:",
          "  - koan_set_overview: Define problem and approach",
          "  - koan_set_constraints: Record constraints",
          "  - koan_set_invisible_knowledge: Document project-specific context",
          "",
          "DECISIONS & RISKS:",
          "  - koan_add_decision, koan_set_decision: Record architectural decisions",
          "  - koan_add_rejected_alternative: Document rejected approaches",
          "  - koan_add_risk: Track implementation risks",
          "",
          "MILESTONES & INTENTS:",
          "  - koan_add_milestone: Create milestones (deployable increments)",
          "  - koan_set_milestone_name/files/flags/requirements/acceptance_criteria/tests: Configure milestones",
          "  - koan_add_intent, koan_set_intent: Define code intents (WHAT to change, not HOW)",
          "",
          "WAVES & STRUCTURE:",
          "  - koan_add_wave, koan_set_wave_milestones: Group milestones into deployment waves",
          "  - koan_add_diagram, koan_set_diagram, koan_add_diagram_node, koan_add_diagram_edge: Visual structure",
          "  - koan_set_readme_entry: Link plan sections to README.md",
          "",
          "Each tool writes to disk immediately. Inspect with koan_get_plan.",
          "",
          "MILESTONES (each deployable increment):",
          "  - Files: exact paths (each file in ONE milestone only)",
          "  - Requirements: specific behaviors",
          "  - Acceptance: testable pass/fail criteria",
          "  - Code Intent: WHAT to change (Developer converts to code_changes later)",
          "  - Tests: type, backing, scenarios",
          "",
          "PARALLELIZATION:",
          "  Vertical slices (parallel) > Horizontal layers (sequential)",
          "  BAD: M1=models, M2=services, M3=controllers (sequential)",
          "  GOOD: M1=auth stack, M2=users stack, M3=posts stack (parallel)",
          "  If file overlap: extract to M0 (foundation) or consolidate",
        ],
        invokeAfter: [
          "WHEN DONE: After completing the instructions above, call koan_next_step to validate.",
          "Do NOT call this tool until you have used the plan mutation tools.",
        ].join("\n"),
      };

    default:
      return { title: "", instructions: [] };
  }
}
