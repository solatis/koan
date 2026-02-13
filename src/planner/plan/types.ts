export interface Decision {
  id: string;
  version: number;
  decision: string;
  reasoning_chain: string;
}

export interface RejectedAlternative {
  id: string;
  alternative: string;
  rejection_reason: string;
  decision_ref: string;
}

export interface Risk {
  id: string;
  risk: string;
  mitigation: string;
  anchor?: string | null;
  decision_ref?: string | null;
}

export interface PlanningContext {
  decision_log: Decision[];
  rejected_alternatives: RejectedAlternative[];
  constraints: string[];
  known_risks: Risk[];
}

export interface InvisibleKnowledge {
  system: string;
  invariants: string[];
  tradeoffs: string[];
}

export interface Overview {
  problem: string;
  approach: string;
}

export interface CodeIntent {
  id: string;
  version: number;
  file: string;
  function?: string | null;
  behavior: string;
  decision_refs: string[];
}

export interface CodeChange {
  id: string;
  version: number;
  intent_ref: string | null;
  file: string;
  diff: string;
  doc_diff: string;
  comments: string;
}

export interface Docstring {
  function: string;
  docstring: string;
}

export interface FunctionBlock {
  function: string;
  comment: string;
  decision_ref: string | null;
  source: string | null;
}

export interface InlineComment {
  location: string;
  comment: string;
  decision_ref: string | null;
  source: string | null;
}

// DEPRECATED per reference schema. Kept for backwards compatibility with
// Python-based planner plans. New plans use CodeChange.doc_diff.
export interface Documentation {
  module_comment: string | null;
  docstrings: Docstring[];
  function_blocks: FunctionBlock[];
  inline_comments: InlineComment[];
}

// DEPRECATED per reference schema. Kept for backwards compatibility with
// Python-based planner plans. New plans use CodeChange.doc_diff.
export interface ReadmeEntry {
  path: string;
  content: string;
}

export interface DiagramNode {
  id: string;
  label: string;
  type: string | null;
}

export interface DiagramEdge {
  source: string;
  target: string;
  label: string;
  protocol: string | null;
}

export interface DiagramGraph {
  id: string;
  type: "architecture" | "state" | "sequence" | "dataflow";
  scope: string;
  title: string;
  nodes: DiagramNode[];
  edges: DiagramEdge[];
  ascii_render: string | null;
}

export interface Milestone {
  id: string;
  version: number;
  number: number;
  name: string;
  files: string[];
  flags: string[];
  requirements: string[];
  acceptance_criteria: string[];
  tests: string[];
  code_intents: CodeIntent[];
  code_changes: CodeChange[];
  documentation: Documentation;
  is_documentation_only: boolean;
  delegated_to: string | null;
}

export interface Wave {
  id: string;
  milestones: string[];
}

export interface Plan {
  plan_id: string;
  created_at: string;
  frozen_at: string | null;
  overview: Overview;
  planning_context: PlanningContext;
  invisible_knowledge: InvisibleKnowledge;
  milestones: Milestone[];
  waves: Wave[];
  diagram_graphs: DiagramGraph[];
  readme_entries: ReadmeEntry[];
}

export function createEmptyPlan(planId: string): Plan {
  return {
    plan_id: planId,
    created_at: new Date().toISOString(),
    frozen_at: null,
    overview: { problem: "", approach: "" },
    planning_context: {
      decision_log: [],
      rejected_alternatives: [],
      constraints: [],
      known_risks: [],
    },
    invisible_knowledge: { system: "", invariants: [], tradeoffs: [] },
    milestones: [],
    waves: [],
    diagram_graphs: [],
    readme_entries: [],
  };
}

function pad3(n: number): string {
  return String(n).padStart(3, "0");
}

export function nextDecisionId(p: Plan): string {
  return `DL-${pad3(p.planning_context.decision_log.length + 1)}`;
}

export function nextMilestoneId(p: Plan): string {
  return `M-${pad3(p.milestones.length + 1)}`;
}

export function nextIntentId(m: Milestone): string {
  const num = m.code_intents.length + 1;
  return `CI-${m.id}-${pad3(num)}`;
}

export function nextRiskId(p: Plan): string {
  return `R-${pad3(p.planning_context.known_risks.length + 1)}`;
}

export function nextRejectedAltId(p: Plan): string {
  return `RA-${pad3(p.planning_context.rejected_alternatives.length + 1)}`;
}

export function nextWaveId(p: Plan): string {
  return `W-${pad3(p.waves.length + 1)}`;
}

export function nextDiagramId(p: Plan): string {
  return `DIAG-${pad3(p.diagram_graphs.length + 1)}`;
}

export function nextChangeId(m: Milestone): string {
  const num = m.code_changes.length + 1;
  return `CC-${m.id}-${pad3(num)}`;
}
