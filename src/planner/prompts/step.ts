// Step prompt assembly for koan workflows.
//
// The `thoughts` parameter on koan_complete_step captures the model's
// work output (analysis, review, findings) as a tool parameter. This
// avoids requiring the model to produce text + tool_call in one
// response, which some models (e.g. GPT-5-codex) cannot do.

export interface StepGuidance {
  title: string;
  instructions: string[];
  // Custom invoke-after directive. When omitted, formatStep
  // appends the default koan_complete_step directive.
  // Terminal steps override this (e.g., step 6 plan validation).
  invokeAfter?: string;
}

const DEFAULT_INVOKE = [
  "WHEN DONE: Call koan_complete_step with your findings in the `thoughts` parameter.",
  "Do NOT call this tool until the work described in this step is finished.",
].join("\n");

export function formatStep(g: StepGuidance): string {
  const header = `${g.title}\n${"=".repeat(g.title.length)}\n\n`;
  const body = g.instructions.join("\n");
  const invoke = g.invokeAfter ?? DEFAULT_INVOKE;
  return `${header}${body}\n\n${invoke}`;
}
