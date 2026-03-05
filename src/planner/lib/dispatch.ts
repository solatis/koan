// Shared workflow dispatch and plan-ref infrastructure.
// Decouples static tool registration (init-time) from dynamic phase routing (runtime).
// All mutable slots are null by default; phases hook/unhook on begin/end.

// -- Result types --

export interface StepResult {
  ok: boolean;
  prompt?: string;
  error?: string;
}

// -- Dispatch --

export interface WorkflowDispatch {
  onCompleteStep: ((thoughts?: string) => StepResult | Promise<StepResult>) | null;
}

export function createDispatch(): WorkflowDispatch {
  return { onCompleteStep: null };
}

// Decouples tool registration (init-time, before _buildRuntime) from
// plan directory creation (runtime, after flags available). Same
// indirection pattern as WorkflowDispatch.
export interface PlanRef {
  dir: string | null;
  qrPhase: string | null;
}

export function createPlanRef(): PlanRef {
  return { dir: null, qrPhase: null };
}

// Decouples tool registration (init-time) from subagent directory
// resolution (runtime, after flags available). Same indirection
// pattern as PlanRef.
export interface SubagentRef {
  dir: string | null;
}

export function createSubagentRef(): SubagentRef {
  return { dir: null };
}

// Sets a dispatch slot. Throws if the slot is already occupied --
// prevents silent misrouting when two phases attempt to claim
// the same tool.
export function hookDispatch<K extends keyof WorkflowDispatch>(
  dispatch: WorkflowDispatch,
  key: K,
  handler: NonNullable<WorkflowDispatch[K]>,
): void {
  if (dispatch[key] !== null) {
    throw new Error(`dispatch.${String(key)} is already hooked`);
  }
  // TypeScript cannot verify generic key-value assignment.
  // Call-site generic constraint (handler: NonNullable<WorkflowDispatch[K]>)
  // ensures type safety; collision guard above prevents double-hooking.
  (dispatch as any)[key] = handler;
}

export function unhookDispatch(
  dispatch: WorkflowDispatch,
  key: keyof WorkflowDispatch,
): void {
  (dispatch as any)[key] = null;
}
