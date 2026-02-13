export interface ContextData {
  task_spec: string[];
  constraints: string[];
  entry_points: string[];
  rejected_alternatives: string[];
  current_understanding: string[];
  assumptions: string[];
  invisible_knowledge: string[];
  reference_docs: string[];
}

export const CONTEXT_KEYS: ReadonlyArray<keyof ContextData> = [
  "task_spec",
  "constraints",
  "entry_points",
  "rejected_alternatives",
  "current_understanding",
  "assumptions",
  "invisible_knowledge",
  "reference_docs",
];
