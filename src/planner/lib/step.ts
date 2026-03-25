// Step prompt assembly for koan phase workflows.
//
// formatStep() wraps step guidance with a header and a mandatory invoke-after
// directive. The directive at the END of every step is as important as the
// boot prompt at the beginning: primacy (first message) establishes the
// koan_complete_step habit; recency (last thing in each step) reinforces it.
// Together they make the calling pattern robust across model capability levels.
//
// ## The `thoughts` parameter invariant
//
// `thoughts` on koan_complete_step is an ESCAPE HATCH, not a data channel.
//
// Many LLMs cannot produce both text output and a tool call in the same
// response. Without `thoughts`, these models would have no way to do
// chain-of-thought reasoning (lists, chain-of-draft, working through items
// one-by-one) while still calling koan_complete_step to advance the workflow.
// The parameter gives them a place to write intermediate reasoning.
//
// Extended thinking / <thinking> blocks exist but are insufficient: not all
// models support them, they are not visible in audit logs, and some reasoning
// patterns (e.g., "write down a list of X items and evaluate each") work
// better as explicit text the model can reference in subsequent turns.
//
// THE INVARIANT: `thoughts` must NEVER be actively used to capture task
// output. No summaries, no reports, no structured data. Step instructions
// must NOT say "put your findings in the `thoughts` parameter" or similar.
// Task output goes to files (findings.md, landscape.md, plan.md, etc.).
// The LLM may fill `thoughts` with whatever it wants — that's fine — but
// no prompt should instruct it to put specific content there.
//
// A 500-char prefix of `thoughts` is captured in the audit projection as
// `completionSummary` for UI display — this is incidental, not a contract.

export interface StepGuidance {
  title: string;
  instructions: string[];
  // Override the default "WHEN DONE: Call koan_complete_step..." directive.
  // Use for terminal steps that must call a domain tool (e.g. koan_select_story)
  // before koan_complete_step, or for steps where the completion signal differs.
  invokeAfter?: string;
}

// Appended to every step that doesn't override invokeAfter.
// Positioned last for recency — LLMs weight end-of-context instructions heavily.
//
// NOTE: The default invoke deliberately does NOT mention the `thoughts` parameter.
// See the invariant above — `thoughts` is an escape hatch for models that can't
// mix text + tool_call, not a data channel. Prompts must not instruct the LLM
// to put specific content there.
const DEFAULT_INVOKE = [
  "WHEN DONE: Call koan_complete_step to advance to the next step.",
  "Do NOT call this tool until the work described in this step is finished.",
].join("\n");

export function formatStep(g: StepGuidance): string {
  const header = `${g.title}\n${"=".repeat(g.title.length)}\n\n`;
  const body = g.instructions.join("\n");
  const invoke = g.invokeAfter ?? DEFAULT_INVOKE;
  return `${header}${body}\n\n${invoke}`;
}
