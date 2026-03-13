// Step prompt assembly for koan phase workflows.
//
// The `thoughts` parameter on koan_complete_step captures the model's work output
// (analysis, review, findings) as a tool parameter rather than text output. This
// ensures models that can't mix text + tool_call in one response still advance
// the workflow.

export interface StepGuidance {
  title: string;
  instructions: string[];
  // Custom invoke-after directive. When omitted, formatStep appends the default
  // koan_complete_step directive. Terminal steps may override this.
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
