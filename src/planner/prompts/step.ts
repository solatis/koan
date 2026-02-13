// Step prompt assembly for koan workflows.
//
// Format matches the reference planner's format_step() in
// skills/lib/workflow/prompts/step.py. Both use "NEXT STEP:"
// directives. Reference uses "Command:" for shell execution.
// Koan uses "Tool:" -- tool results are synchronous within
// the agent loop (deterministic delivery regardless of -p mode).
//
// Why strengthen invoke-after? The original weak format ("Now call
// koan_next_step.") produced skipped steps. Strengthened format
// mirrors reference planner's explicit directive structure.

export interface StepGuidance {
  title: string;
  instructions: string[];
  // Custom invoke-after directive. When omitted, formatStep
  // appends the default koan_next_step directive.
  // Terminal steps override this (e.g., step 6 plan validation).
  invokeAfter?: string;
}

// Default invoke-after: conditional gate for koan_next_step.
// "WHEN DONE" + "Do NOT call until" creates a two-part gate:
// the LLM must complete work before advancing. Unconditional
// imperatives ("Execute this tool now.") cause immediate tool
// calls because tool calls with empty params have zero friction
// (unlike shell commands which require mechanical copy-paste).
const DEFAULT_INVOKE = [
  "WHEN DONE: After completing the instructions above, call koan_next_step to advance.",
  "Do NOT call this tool until the work described in this step is finished.",
].join("\n");

export function formatStep(g: StepGuidance): string {
  const header = `${g.title}\n${"=".repeat(g.title.length)}\n\n`;
  const body = g.instructions.join("\n");
  const invoke = g.invokeAfter ?? DEFAULT_INVOKE;
  return `${header}${body}\n\n${invoke}`;
}
