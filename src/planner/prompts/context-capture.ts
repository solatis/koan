import type { StepGuidance } from "./step.js";

export function draftGuidance(taskDescription: string): StepGuidance {
  return {
    title: "Context Capture: Draft",
    instructions: [
      "You are about to begin a structured planning workflow. Before any formalization, think carefully through the full context of this task.",
      "",
      `Task: ${taskDescription}`,
      "",
      "Your primary source is the conversation so far. Most of what you need is already here.",
      "",
      "You MAY use tools during this phase if -- and only if -- a specific lookup would",
      "resolve genuine uncertainty that materially affects planning. Examples of justified reads:",
      "- Confirming an API signature you are unsure about",
      "- Checking whether a file or module actually exists",
      "- Reading a config that determines a key constraint",
      "",
      "Do NOT explore speculatively. If you can draft a confident answer from context alone, do so.",
      "",
      "Think through each of these dimensions:",
      "",
      "- What exactly is being asked? What is the user's goal? What is in scope and what is explicitly not?",
      "- What technical constraints apply to the task itself -- API contracts, performance targets, compatibility requirements, architectural rules? Only include constraints that are specific to this task. Do not include general tool usage instructions, coding style guides, or editor/IDE conventions.",
      "- Which files, modules, or entry points in the codebase are relevant? If this is greenfield work with no existing code, say so.",
      "- Were any alternative approaches discussed and rejected during this session? Why?",
      "- What is your current understanding of the system or domain involved?",
      "- What assumptions are you making that haven't been verified? How confident are you in each?",
      "- Is there any implicit design knowledge -- invariants, rationale, accepted tradeoffs -- that should be preserved for downstream work?",
      "- Are there reference documents or specs in the project that apply?",
      "",
      "For each dimension, note your confidence:",
      "- HIGH: you have direct evidence from this session",
      "- LOW: you are extrapolating or guessing",
      "",
      "Flag any LOW-confidence point where a single targeted read would raise it to HIGH.",
      "This is a working document, not a final artifact.",
      "",
      "Put your full draft analysis in the `thoughts` parameter when calling koan_complete_step.",
    ],
  };
}

export function verifyGuidance(): StepGuidance {
  return {
    title: "Context Capture: Verify",
    instructions: [
      "Review the draft you just wrote. Check three things:",
      "",
      "1. Completeness: scan each dimension above. Is anything missing?",
      "2. Accuracy: are any items wrong, speculative, or conflating things?",
      "3. Phrasing: would a downstream agent understand without ambiguity?",
      "",
      "Rewrite the draft with corrections. If nothing needs changing, reproduce it as-is.",
      "Do not use exploration tools during this review.",
      "",
      "Put your revised analysis in the `thoughts` parameter when calling koan_complete_step.",
    ],
  };
}

export interface RefinePromptOptions {
  attempt: number;
  maxAttempts: number;
  feedback: string[];
}

export function refineGuidance(opts: RefinePromptOptions): StepGuidance {
  const instructions: string[] = [];
  if (opts.attempt > 1) {
    instructions.push(`Retry (attempt ${opts.attempt} of ${opts.maxAttempts}).`);
  }
  instructions.push(
    "Now call the `koan_store_context` tool with the verified context.",
    "The tool's parameter schema defines exactly what fields are needed.",
  );
  if (opts.feedback.length > 0) {
    instructions.push("", "Address these issues from the previous attempt:");
    for (const item of opts.feedback) {
      instructions.push(`- ${item}`);
    }
  }
  return {
    title: "Context Capture: Refine",
    instructions,
    // Refine completes with koan_store_context, not koan_next_step.
    invokeAfter: [
      "WHEN DONE: After completing the instructions above, call koan_store_context with the verified context data.",
      "Do NOT call this tool until you have prepared the structured context.",
    ].join("\n"),
  };
}
