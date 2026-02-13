import type { ContextData } from "./types.js";

export type WorkflowPhase =
  | "idle"
  | "context"
  | "context-complete"
  | "context-failed"
  | "architect-running"
  | "architect-failed"
  | "plan-design-complete";

export interface PlanInfo {
  id: string;
  directory: string;
  createdAt: string;
  metadataPath: string;
}

export interface ContextCaptureState {
  readonly maxAttempts: number;
  active: boolean;
  subPhase: "drafting" | "verifying" | "refining";
  attempt: number;
  taskDescription: string;
  planId: string;
  planDirectory: string;
  contextFilePath: string;
  lastPrompt: string | null;
  feedback: string[];
  data?: ContextData;
  lastRawContent?: string;
}

export interface WorkflowState {
  phase: WorkflowPhase;
  taskDescription: string | null;
  plan: PlanInfo | null;
  context: ContextCaptureState | null;
}

export function createInitialState(): WorkflowState {
  return {
    phase: "idle",
    taskDescription: null,
    plan: null,
    context: null,
  };
}

export function resetContextState(state: WorkflowState): void {
  state.context = null;
  if (
    state.phase === "context" ||
    state.phase === "context-failed" ||
    state.phase === "context-complete" ||
    state.phase === "architect-failed" ||
    state.phase === "plan-design-complete"
  ) {
    state.phase = "idle";
  }
}

export function initializePlanState(state: WorkflowState, plan: PlanInfo, taskDescription: string): void {
  state.plan = plan;
  state.taskDescription = taskDescription;
  resetContextState(state);
}
