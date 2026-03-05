import type { StepGuidance } from "../../lib/step.js";
import { buildPlanDesignContextTrigger } from "../../lib/conversation-trigger.js";
import { CONVENTIONS_DIR } from "../../lib/resources.js";
import { loadAgentPrompt } from "../../lib/agent-prompts.js";

export const STEP_NAMES: Record<1 | 2 | 3 | 4 | 5 | 6, string> = {
  1: "Task Analysis & Exploration Planning",
  2: "Codebase Exploration",
  3: "Testing Strategy Discovery",
  4: "Approach Generation",
  5: "Ambiguity Resolution",
  6: "Milestone Definition & Plan Writing",
};

export async function loadPlanDesignSystemPrompt(): Promise<string> {
  return loadAgentPrompt("architect");
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
    "Complete the work described, then call koan_complete_step.",
    "Put your findings in the `thoughts` parameter of koan_complete_step.",
    "The tool result contains the next step's instructions.",
    "In step 6, use plan mutation tools, then call koan_complete_step.",
    "",
    "CRITICAL: Do the actual work described in each step BEFORE calling",
    "koan_complete_step. Read files, explore code, analyze. Do not skip.",
    "",
    "DECISION PROVENANCE:",
    "Every decision requires a source tag. Valid sources:",
    "  code:<path> -- derived from reading source code",
    "  docs:<path> -- derived from project documentation",
    "  user:ask -- user answered via koan_ask_question",
    "  user:conversation -- user stated in captured conversation",
    "  inference -- inferred from patterns (last resort; see step 5 rules)",
    "If you cannot ground a decision in code or documentation, use",
    "koan_ask_question. Ambiguity resolved by asking is better than",
    "ambiguity resolved by assumption.",
  ].join("\n");
}

export function planDesignStepGuidance(
  step: 1 | 2 | 3 | 4 | 5 | 6,
  conversationPath?: string,
): StepGuidance {
  switch (step) {
    case 1:
      return {
        title: "Step 1: Task Analysis & Exploration Planning",
        instructions: [
          ...buildPlanDesignContextTrigger(conversationPath ?? "<planDir>/conversation.jsonl"),
          "",
          "After absorbing the task intent, identify:",
          "  - What needs to change (files, modules, behavior)",
          "  - What exploration is needed (patterns, constraints, existing code)",
          "  - What directories/files are relevant",
          "",
          "Read project context files to understand structure:",
          "  - Project root CLAUDE.md",
          "  - Subdirectory CLAUDE.md files in relevant areas",
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
          "Read convention files as needed (use absolute paths below):",
          `  - ${CONVENTIONS_DIR}/structural.md (architectural patterns)`,
          `  - ${CONVENTIONS_DIR}/temporal.md (comment hygiene)`,
          `  - ${CONVENTIONS_DIR}/diff-format.md (diff specification)`,
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
          `  - ${CONVENTIONS_DIR}/structural.md domain='testing-strategy'`,
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
          "",
          "DECISION INVENTORY:",
          "For each approach, identify the implicit decisions it makes.",
          "For each decision, note the source:",
          "  - code:<path> -- forced by existing codebase (cite file)",
          "  - docs:<path> -- specified in project docs (cite file)",
          "  - user:conversation -- user stated preference in conversation",
          "  - inference -- your judgment (requires strong reasoning_chain)",
          "  - UNRESOLVED -- no clear source; flag for step 5",
        ],
      };

    case 5:
      return {
        title: "Step 5: Ambiguity Resolution",
        instructions: [
          "Review the decision inventory from step 4.",
          "For every decision marked UNRESOLVED or sourced as inference:",
          "  1. Can it be grounded in code or docs? Read them.",
          "  2. If still unsourced, ask the user via koan_ask_question.",
          "",
          "USE koan_ask_question WHEN:",
          "  - Multiple approaches have comparable tradeoffs, no codebase precedent",
          "  - A policy default (timeout, capacity, retry, failure mode) has no value",
          "  - Migration path or abstraction boundary not dictated by code",
          "",
          "DO NOT ASK WHEN:",
          "  - Codebase establishes a clear pattern (source: code:<path>)",
          "  - Project docs specify the approach (source: docs:<path>)",
          "  - Only one approach is technically viable",
          "  - The choice follows directly from an already-sourced decision",
          "",
          "INFERENCE RULES (source: inference):",
          "  Acceptable: airtight reasoning, no viable alternative, follows from",
          "  existing constraints, standard practice with one correct answer.",
          "  NOT acceptable: hedging language, policy defaults, public API choices,",
          "  or any decision where a senior engineer might reasonably disagree.",
          "",
          "Good questions offer concrete options grounded in codebase evidence:",
          "  BAD:  'How should we handle errors?'",
          "  GOOD: 'Error propagation: (A) return Result<T,E> matching src/foo.ts,",
          "         (B) throw + catch at boundary matching src/bar.ts'",
          "",
          "FAST PATH: If all decisions have code/docs/conversation sources,",
          "skip asking and record this finding.",
          "",
          "After resolving, every decision has a concrete source. No UNRESOLVED.",
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
          "Every koan_add_decision call MUST include a source parameter:",
          "  - code:<path> -- derived from existing code (cite file)",
          "  - docs:<path> -- from project documentation (cite file)",
          "  - user:ask -- asked the user via koan_ask_question",
          "  - user:conversation -- user stated in original conversation",
          "  - inference -- architect judgment (use sparingly; needs strong chain)",
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
          "WHEN DONE: Call koan_complete_step to validate. Put a summary of what you built in the `thoughts` parameter.",
          "Do NOT call this tool until you have used the plan mutation tools.",
        ].join("\n"),
      };

    default:
      return { title: "", instructions: [] };
  }
}
