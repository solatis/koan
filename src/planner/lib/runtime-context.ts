// RuntimeContext replaces the old PlanRef + SubagentRef + WorkflowDispatch triple.
// Set once during before_agent_start; tools read from it at call time. The mutable-ref
// pattern accommodates pi's extension lifecycle: tools register at init before state exists.
//
// onCompleteStep return value:
//   string  → next step's formatted prompt (tool returns it to the LLM)
//   null    → phase is complete (tool returns "Phase complete.")
//
// intakeConfidence: set by koan_set_confidence during the intake Reflect step.
//   IntakePhase reads this in getNextStep() to decide whether to loop or advance.
//   Reset to null after each loop-back to enforce re-assessment each iteration.
//
// intakeStep: current step number, kept in sync by IntakePhase.onStepUpdated().
//   The permission fence reads this to block side-effecting tools during the
//   read-only Extract step (step 1).
//
// intakeIteration: current loop iteration (1-based), kept in sync by IntakePhase.
//   The confidence tool uses this when emitting confidence_change audit events.
//
// eventLog: the active EventLog for the current subagent session. Set during
//   before_agent_start after the log file is opened. Tools that need to emit
//   audit events (e.g. koan_set_confidence) read this at call time.

import type { EventLog } from "./audit.js";

export interface RuntimeContext {
  epicDir: string | null;
  subagentDir: string | null;
  onCompleteStep: ((thoughts: string) => Promise<string | null>) | null;
  intakeConfidence: "exploring" | "low" | "medium" | "high" | "certain" | null;
  intakeStep: number;
  intakeIteration: number;
  eventLog: EventLog | null;
}

export function createRuntimeContext(): RuntimeContext {
  return {
    epicDir: null,
    subagentDir: null,
    onCompleteStep: null,
    intakeConfidence: null,
    intakeStep: 0,
    intakeIteration: 1,
    eventLog: null,
  };
}
