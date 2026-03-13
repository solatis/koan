// RuntimeContext replaces the old PlanRef + SubagentRef + WorkflowDispatch triple.
// Set once during before_agent_start; tools read from it at call time. The mutable-ref
// pattern accommodates pi's extension lifecycle: tools register at init before state exists.
//
// onCompleteStep return value:
//   string  → next step's formatted prompt (tool returns it to the LLM)
//   null    → phase is complete (tool returns "Phase complete.")
export interface RuntimeContext {
  epicDir: string | null;
  subagentDir: string | null;
  onCompleteStep: ((thoughts: string) => Promise<string | null>) | null;
}

export function createRuntimeContext(): RuntimeContext {
  return {
    epicDir: null,
    subagentDir: null,
    onCompleteStep: null,
  };
}
