// RuntimeContext replaces the old PlanRef + SubagentRef + WorkflowDispatch triple.
// Set once during before_agent_start; tools read from it at call time. The mutable-ref
// pattern accommodates pi's extension lifecycle: tools register at init before state exists.
//
// onCompleteStep return value:
//   string  -> next step's formatted prompt (tool returns it to the LLM)
//   null    -> phase is complete (tool returns "Phase complete.")
//
// currentStep is kept on RuntimeContext (not on individual phases) because
// BasePhase's permission fence reads it on every tool_call event without
// knowing the active phase type.
//
// eventLog: the active EventLog for the current subagent session. Set during
//   before_agent_start after the log file is opened. Tools that need to emit
//   audit events read this at call time.
//
// phaseInstructions: optional context injected by the workflow orchestrator's
//   decision. Present when the user provided focus instructions during the
//   workflow decision interaction. Absent when the orchestrator is skipped or
//   the user gave no additional direction. Applies uniformly to all phases.

import type { EventLog } from "./event-log.js";

export interface RuntimeContext {
  epicDir: string | null;
  subagentDir: string | null;
  onCompleteStep: ((thoughts: string) => Promise<string | null>) | null;
  currentStep: number;
  eventLog: EventLog | null;
  /** Optional instructions from the workflow orchestrator's decision.
   *  Injected into step 1 guidance when the user provides context during
   *  the workflow decision interaction. */
  phaseInstructions?: string;
}

export function createRuntimeContext(): RuntimeContext {
  return {
    epicDir: null,
    subagentDir: null,
    onCompleteStep: null,
    currentStep: 0,
    eventLog: null,
  };
}
