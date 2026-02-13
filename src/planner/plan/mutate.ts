// Monotonic version counter on entities. No CAS enforcement -- single-writer
// per phase. Counter is for debugging and audit trail, not concurrency control.

import type {
  Plan,
  Decision,
  RejectedAlternative,
  Risk,
  Milestone,
  CodeIntent,
  CodeChange,
  Wave,
  DiagramGraph,
  DiagramNode,
  DiagramEdge,
  ReadmeEntry,
  Overview,
  InvisibleKnowledge,
} from "./types.js";
import {
  nextDecisionId,
  nextMilestoneId,
  nextIntentId,
  nextRiskId,
  nextRejectedAltId,
  nextWaveId,
  nextDiagramId,
  nextChangeId,
} from "./types.js";

// -- Top-level --

export function setOverview(
  p: Plan,
  data: { problem?: string; approach?: string },
): Plan {
  const overview: Overview = {
    problem: data.problem ?? p.overview.problem,
    approach: data.approach ?? p.overview.approach,
  };
  return { ...p, overview };
}

export function setConstraints(p: Plan, constraints: string[]): Plan {
  return {
    ...p,
    planning_context: {
      ...p.planning_context,
      constraints,
    },
  };
}

export function setInvisibleKnowledge(
  p: Plan,
  data: { system?: string; invariants?: string[]; tradeoffs?: string[] },
): Plan {
  const ik: InvisibleKnowledge = {
    system: data.system ?? p.invisible_knowledge.system,
    invariants: data.invariants ?? p.invisible_knowledge.invariants,
    tradeoffs: data.tradeoffs ?? p.invisible_knowledge.tradeoffs,
  };
  return { ...p, invisible_knowledge: ik };
}

// -- Decision --

export function addDecision(
  p: Plan,
  data: { decision: string; reasoning: string },
): { plan: Plan; id: string } {
  const id = nextDecisionId(p);
  const decision: Decision = {
    id,
    version: 1,
    decision: data.decision,
    reasoning_chain: data.reasoning,
  };
  return {
    plan: {
      ...p,
      planning_context: {
        ...p.planning_context,
        decision_log: [...p.planning_context.decision_log, decision],
      },
    },
    id,
  };
}

export function setDecision(
  p: Plan,
  id: string,
  data: { decision?: string; reasoning?: string },
): Plan {
  const idx = p.planning_context.decision_log.findIndex((d) => d.id === id);
  if (idx === -1) throw new Error(`decision ${id} not found`);

  const d = p.planning_context.decision_log[idx];
  const updated: Decision = {
    ...d,
    version: d.version + 1,
    decision: data.decision ?? d.decision,
    reasoning_chain: data.reasoning ?? d.reasoning_chain,
  };

  const log = [...p.planning_context.decision_log];
  log[idx] = updated;

  return {
    ...p,
    planning_context: { ...p.planning_context, decision_log: log },
  };
}

// -- RejectedAlternative --

export function addRejectedAlternative(
  p: Plan,
  data: { alternative: string; rejection_reason: string; decision_ref: string },
): { plan: Plan; id: string } {
  const id = nextRejectedAltId(p);
  const ra: RejectedAlternative = {
    id,
    alternative: data.alternative,
    rejection_reason: data.rejection_reason,
    decision_ref: data.decision_ref,
  };
  return {
    plan: {
      ...p,
      planning_context: {
        ...p.planning_context,
        rejected_alternatives: [
          ...p.planning_context.rejected_alternatives,
          ra,
        ],
      },
    },
    id,
  };
}

export function setRejectedAlternative(
  p: Plan,
  id: string,
  data: {
    alternative?: string;
    rejection_reason?: string;
    decision_ref?: string;
  },
): Plan {
  const idx = p.planning_context.rejected_alternatives.findIndex(
    (r) => r.id === id,
  );
  if (idx === -1) throw new Error(`rejected_alternative ${id} not found`);

  const r = p.planning_context.rejected_alternatives[idx];
  const updated: RejectedAlternative = {
    ...r,
    alternative: data.alternative ?? r.alternative,
    rejection_reason: data.rejection_reason ?? r.rejection_reason,
    decision_ref: data.decision_ref ?? r.decision_ref,
  };

  const list = [...p.planning_context.rejected_alternatives];
  list[idx] = updated;

  return {
    ...p,
    planning_context: { ...p.planning_context, rejected_alternatives: list },
  };
}

// -- Risk --

export function addRisk(
  p: Plan,
  data: {
    risk: string;
    mitigation: string;
    anchor?: string;
    decision_ref?: string;
  },
): { plan: Plan; id: string } {
  const id = nextRiskId(p);
  const risk: Risk = {
    id,
    risk: data.risk,
    mitigation: data.mitigation,
    anchor: data.anchor ?? null,
    decision_ref: data.decision_ref ?? null,
  };
  return {
    plan: {
      ...p,
      planning_context: {
        ...p.planning_context,
        known_risks: [...p.planning_context.known_risks, risk],
      },
    },
    id,
  };
}

export function setRisk(
  p: Plan,
  id: string,
  data: {
    risk?: string;
    mitigation?: string;
    anchor?: string;
    decision_ref?: string;
  },
): Plan {
  const idx = p.planning_context.known_risks.findIndex((r) => r.id === id);
  if (idx === -1) throw new Error(`risk ${id} not found`);

  const r = p.planning_context.known_risks[idx];
  const updated: Risk = {
    ...r,
    risk: data.risk ?? r.risk,
    mitigation: data.mitigation ?? r.mitigation,
    anchor: data.anchor ?? r.anchor,
    decision_ref: data.decision_ref ?? r.decision_ref,
  };

  const list = [...p.planning_context.known_risks];
  list[idx] = updated;

  return {
    ...p,
    planning_context: { ...p.planning_context, known_risks: list },
  };
}

// -- Milestone --

export function addMilestone(
  p: Plan,
  data: {
    name: string;
    files?: string[];
    flags?: string[];
    requirements?: string[];
    acceptance_criteria?: string[];
    tests?: string[];
  },
): { plan: Plan; id: string } {
  const id = nextMilestoneId(p);
  const milestone: Milestone = {
    id,
    version: 1,
    number: p.milestones.length + 1,
    name: data.name,
    files: data.files ?? [],
    flags: data.flags ?? [],
    requirements: data.requirements ?? [],
    acceptance_criteria: data.acceptance_criteria ?? [],
    tests: data.tests ?? [],
    code_intents: [],
    code_changes: [],
    documentation: {
      module_comment: null,
      docstrings: [],
      function_blocks: [],
      inline_comments: [],
    },
    is_documentation_only: false,
    delegated_to: null,
  };
  return {
    plan: {
      ...p,
      milestones: [...p.milestones, milestone],
    },
    id,
  };
}

function updateMilestone(
  p: Plan,
  id: string,
  fn: (m: Milestone) => Milestone,
): Plan {
  const idx = p.milestones.findIndex((m) => m.id === id);
  if (idx === -1) throw new Error(`milestone ${id} not found`);

  const updated = [...p.milestones];
  updated[idx] = fn(p.milestones[idx]);
  return { ...p, milestones: updated };
}

export function setMilestoneName(p: Plan, id: string, name: string): Plan {
  return updateMilestone(p, id, (m) => ({ ...m, version: m.version + 1, name }));
}

export function setMilestoneFiles(p: Plan, id: string, files: string[]): Plan {
  return updateMilestone(p, id, (m) => ({
    ...m,
    version: m.version + 1,
    files,
  }));
}

export function setMilestoneFlags(p: Plan, id: string, flags: string[]): Plan {
  return updateMilestone(p, id, (m) => ({
    ...m,
    version: m.version + 1,
    flags,
  }));
}

export function setMilestoneRequirements(
  p: Plan,
  id: string,
  requirements: string[],
): Plan {
  return updateMilestone(p, id, (m) => ({
    ...m,
    version: m.version + 1,
    requirements,
  }));
}

export function setMilestoneAcceptanceCriteria(
  p: Plan,
  id: string,
  criteria: string[],
): Plan {
  return updateMilestone(p, id, (m) => ({
    ...m,
    version: m.version + 1,
    acceptance_criteria: criteria,
  }));
}

export function setMilestoneTests(p: Plan, id: string, tests: string[]): Plan {
  return updateMilestone(p, id, (m) => ({
    ...m,
    version: m.version + 1,
    tests,
  }));
}

// -- CodeIntent --

export function addIntent(
  p: Plan,
  data: {
    milestone: string;
    file: string;
    function?: string;
    behavior: string;
    decision_refs?: string[];
  },
): { plan: Plan; id: string } {
  const idx = p.milestones.findIndex((m) => m.id === data.milestone);
  if (idx === -1) throw new Error(`milestone ${data.milestone} not found`);

  const m = p.milestones[idx];
  const id = nextIntentId(m);
  const intent: CodeIntent = {
    id,
    version: 1,
    file: data.file,
    function: data.function ?? null,
    behavior: data.behavior,
    decision_refs: data.decision_refs ?? [],
  };

  const updated = [...p.milestones];
  updated[idx] = {
    ...m,
    code_intents: [...m.code_intents, intent],
  };

  return {
    plan: { ...p, milestones: updated },
    id,
  };
}

export function setIntent(
  p: Plan,
  id: string,
  data: {
    file?: string;
    function?: string;
    behavior?: string;
    decision_refs?: string[];
  },
): Plan {
  for (let i = 0; i < p.milestones.length; i++) {
    const m = p.milestones[i];
    const ciIdx = m.code_intents.findIndex((ci) => ci.id === id);
    if (ciIdx !== -1) {
      const ci = m.code_intents[ciIdx];
      const updated: CodeIntent = {
        ...ci,
        version: ci.version + 1,
        file: data.file ?? ci.file,
        function: data.function ?? ci.function,
        behavior: data.behavior ?? ci.behavior,
        decision_refs: data.decision_refs ?? ci.decision_refs,
      };

      const intents = [...m.code_intents];
      intents[ciIdx] = updated;

      const milestones = [...p.milestones];
      milestones[i] = { ...m, code_intents: intents };

      return { ...p, milestones };
    }
  }
  throw new Error(`intent ${id} not found`);
}

// -- CodeChange --

export function addChange(
  p: Plan,
  data: {
    milestone: string;
    file: string;
    intent_ref?: string;
    diff?: string;
    doc_diff?: string;
    comments?: string;
  },
): { plan: Plan; id: string } {
  const idx = p.milestones.findIndex((m) => m.id === data.milestone);
  if (idx === -1) throw new Error(`milestone ${data.milestone} not found`);

  const m = p.milestones[idx];
  const id = nextChangeId(m);
  const change: CodeChange = {
    id,
    version: 1,
    intent_ref: data.intent_ref ?? null,
    file: data.file,
    diff: data.diff ?? "",
    doc_diff: data.doc_diff ?? "",
    comments: data.comments ?? "",
  };

  const updated = [...p.milestones];
  updated[idx] = {
    ...m,
    code_changes: [...m.code_changes, change],
  };

  return {
    plan: { ...p, milestones: updated },
    id,
  };
}

function updateChange(
  p: Plan,
  id: string,
  fn: (c: CodeChange) => CodeChange,
): Plan {
  for (let i = 0; i < p.milestones.length; i++) {
    const m = p.milestones[i];
    const ccIdx = m.code_changes.findIndex((cc) => cc.id === id);
    if (ccIdx !== -1) {
      const changes = [...m.code_changes];
      changes[ccIdx] = fn(m.code_changes[ccIdx]);

      const milestones = [...p.milestones];
      milestones[i] = { ...m, code_changes: changes };

      return { ...p, milestones };
    }
  }
  throw new Error(`code_change ${id} not found`);
}

export function setChangeDiff(p: Plan, id: string, diff: string): Plan {
  return updateChange(p, id, (c) => ({ ...c, version: c.version + 1, diff }));
}

export function setChangeDocDiff(p: Plan, id: string, doc_diff: string): Plan {
  return updateChange(p, id, (c) => ({
    ...c,
    version: c.version + 1,
    doc_diff,
  }));
}

export function setChangeComments(p: Plan, id: string, comments: string): Plan {
  return updateChange(p, id, (c) => ({
    ...c,
    version: c.version + 1,
    comments,
  }));
}

export function setChangeFile(p: Plan, id: string, file: string): Plan {
  return updateChange(p, id, (c) => ({ ...c, version: c.version + 1, file }));
}

export function setChangeIntentRef(
  p: Plan,
  id: string,
  intent_ref: string,
): Plan {
  return updateChange(p, id, (c) => ({
    ...c,
    version: c.version + 1,
    intent_ref,
  }));
}

// -- Wave --

export function addWave(
  p: Plan,
  data: { milestones: string[] },
): { plan: Plan; id: string } {
  const id = nextWaveId(p);
  const wave: Wave = {
    id,
    milestones: data.milestones,
  };
  return {
    plan: {
      ...p,
      waves: [...p.waves, wave],
    },
    id,
  };
}

export function setWaveMilestones(
  p: Plan,
  id: string,
  milestones: string[],
): Plan {
  const idx = p.waves.findIndex((w) => w.id === id);
  if (idx === -1) throw new Error(`wave ${id} not found`);

  const updated = [...p.waves];
  updated[idx] = { ...p.waves[idx], milestones };

  return { ...p, waves: updated };
}

// -- Diagram --

export function addDiagram(
  p: Plan,
  data: {
    type: "architecture" | "state" | "sequence" | "dataflow";
    scope: string;
    title: string;
  },
): { plan: Plan; id: string } {
  const id = nextDiagramId(p);
  const diagram: DiagramGraph = {
    id,
    type: data.type,
    scope: data.scope,
    title: data.title,
    nodes: [],
    edges: [],
    ascii_render: null,
  };
  return {
    plan: {
      ...p,
      diagram_graphs: [...p.diagram_graphs, diagram],
    },
    id,
  };
}

export function setDiagram(
  p: Plan,
  id: string,
  data: { title?: string; scope?: string; ascii_render?: string },
): Plan {
  const idx = p.diagram_graphs.findIndex((d) => d.id === id);
  if (idx === -1) throw new Error(`diagram ${id} not found`);

  const d = p.diagram_graphs[idx];
  const updated: DiagramGraph = {
    ...d,
    title: data.title ?? d.title,
    scope: data.scope ?? d.scope,
    ascii_render: data.ascii_render ?? d.ascii_render,
  };

  const diagrams = [...p.diagram_graphs];
  diagrams[idx] = updated;

  return { ...p, diagram_graphs: diagrams };
}

export function addDiagramNode(
  p: Plan,
  diagramId: string,
  data: { id: string; label: string; type?: string },
): Plan {
  const idx = p.diagram_graphs.findIndex((d) => d.id === diagramId);
  if (idx === -1) throw new Error(`diagram ${diagramId} not found`);

  const d = p.diagram_graphs[idx];
  const node: DiagramNode = {
    id: data.id,
    label: data.label,
    type: data.type ?? null,
  };

  const diagrams = [...p.diagram_graphs];
  diagrams[idx] = {
    ...d,
    nodes: [...d.nodes, node],
  };

  return { ...p, diagram_graphs: diagrams };
}

export function addDiagramEdge(
  p: Plan,
  diagramId: string,
  data: { source: string; target: string; label: string; protocol?: string },
): Plan {
  const idx = p.diagram_graphs.findIndex((d) => d.id === diagramId);
  if (idx === -1) throw new Error(`diagram ${diagramId} not found`);

  const d = p.diagram_graphs[idx];
  const edge: DiagramEdge = {
    source: data.source,
    target: data.target,
    label: data.label,
    protocol: data.protocol ?? null,
  };

  const diagrams = [...p.diagram_graphs];
  diagrams[idx] = {
    ...d,
    edges: [...d.edges, edge],
  };

  return { ...p, diagram_graphs: diagrams };
}

// -- ReadmeEntry --

export function setReadmeEntry(p: Plan, path: string, content: string): Plan {
  const idx = p.readme_entries.findIndex((r) => r.path === path);
  const entry: ReadmeEntry = { path, content };

  if (idx === -1) {
    return {
      ...p,
      readme_entries: [...p.readme_entries, entry],
    };
  }

  const entries = [...p.readme_entries];
  entries[idx] = entry;
  return { ...p, readme_entries: entries };
}
