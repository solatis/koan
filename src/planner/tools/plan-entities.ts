// Every tool follows load-mutate-save: loadPlan -> pure mutation -> savePlan.
// Disk is single source of truth. Single-writer assumption per phase.
// Feedback messages prevent the LLM from skipping tools (prior architecture
// returned opaque JSON).
//
// Static<TParams> derives the TypeScript type from the TypeBox schema at
// compile time, making type casts unnecessary. The registerTool generic
// propagates the schema type through to the execute callback.

import { Type, type Static, type TSchema } from "@sinclair/typebox";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import type { PlanRef } from "./dispatch.js";
import { loadPlan, savePlan } from "../plan/serialize.js";
import type { Plan } from "../plan/types.js";
import {
  addDecision,
  setDecision,
  addRejectedAlternative,
  setRejectedAlternative,
  addRisk,
  setRisk,
  addMilestone,
  setMilestoneName,
  setMilestoneFiles,
  setMilestoneFlags,
  setMilestoneRequirements,
  setMilestoneAcceptanceCriteria,
  setMilestoneTests,
  addIntent,
  setIntent,
  addChange,
  setChangeDiff,
  setChangeDocDiff,
  setChangeComments,
  setChangeFile,
  setChangeIntentRef,
  addWave,
  setWaveMilestones,
  addDiagram,
  setDiagram,
  addDiagramNode,
  addDiagramEdge,
  setReadmeEntry,
} from "../plan/mutate.js";

function planTool<TParams extends TSchema>(
  pi: ExtensionAPI,
  planRef: PlanRef,
  opts: {
    name: string;
    label: string;
    description: string;
    parameters: TParams;
    execute: (plan: Plan, params: Static<TParams>) => { plan: Plan; message: string };
  },
): void {
  pi.registerTool({
    name: opts.name,
    label: opts.label,
    description: opts.description,
    parameters: opts.parameters,
    async execute(_toolCallId, params) {
      if (!planRef.dir) throw new Error("No plan directory is active.");
      const plan = await loadPlan(planRef.dir);
      const result = opts.execute(plan, params);
      await savePlan(result.plan, planRef.dir);
      return {
        content: [{ type: "text" as const, text: result.message }],
        details: undefined,
      };
    },
  });
}

export function registerPlanEntityTools(
  pi: ExtensionAPI,
  planRef: PlanRef,
): void {
  // -- Decision --
  planTool(pi, planRef, {
    name: "koan_add_decision",
    label: "Add decision",
    description: "Add decision to decision log.",
    parameters: Type.Object({
      decision: Type.String(),
      reasoning: Type.String(),
    }),
    execute: (p, params) => {
      const r = addDecision(p, params);
      return {
        plan: r.plan,
        message: `Added decision ${r.id}: "${params.decision}"`,
      };
    },
  });

  planTool(pi, planRef, {
    name: "koan_set_decision",
    label: "Update decision",
    description: "Update existing decision by ID.",
    parameters: Type.Object({
      id: Type.String(),
      decision: Type.Optional(Type.String()),
      reasoning: Type.Optional(Type.String()),
    }),
    execute: (p, params) => {
      const updated = setDecision(p, params.id, params);
      return {
        plan: updated,
        message: `Updated decision ${params.id}`,
      };
    },
  });

  // -- RejectedAlternative --
  planTool(pi, planRef, {
    name: "koan_add_rejected_alternative",
    label: "Add rejected alternative",
    description: "Add rejected alternative to decision log.",
    parameters: Type.Object({
      alternative: Type.String(),
      rejection_reason: Type.String(),
      decision_ref: Type.String(),
    }),
    execute: (p, params) => {
      const r = addRejectedAlternative(p, params);
      return {
        plan: r.plan,
        message: `Added rejected alternative ${r.id}`,
      };
    },
  });

  planTool(pi, planRef, {
    name: "koan_set_rejected_alternative",
    label: "Update rejected alternative",
    description: "Update existing rejected alternative by ID.",
    parameters: Type.Object({
      id: Type.String(),
      alternative: Type.Optional(Type.String()),
      rejection_reason: Type.Optional(Type.String()),
      decision_ref: Type.Optional(Type.String()),
    }),
    execute: (p, params) => {
      const updated = setRejectedAlternative(p, params.id, params);
      return {
        plan: updated,
        message: `Updated rejected alternative ${params.id}`,
      };
    },
  });

  // -- Risk --
  planTool(pi, planRef, {
    name: "koan_add_risk",
    label: "Add risk",
    description: "Add risk to known risks.",
    parameters: Type.Object({
      risk: Type.String(),
      mitigation: Type.String(),
      anchor: Type.Optional(Type.String()),
      decision_ref: Type.Optional(Type.String()),
    }),
    execute: (p, params) => {
      const r = addRisk(p, params);
      return {
        plan: r.plan,
        message: `Added risk ${r.id}: "${params.risk}"`,
      };
    },
  });

  planTool(pi, planRef, {
    name: "koan_set_risk",
    label: "Update risk",
    description: "Update existing risk by ID.",
    parameters: Type.Object({
      id: Type.String(),
      risk: Type.Optional(Type.String()),
      mitigation: Type.Optional(Type.String()),
      anchor: Type.Optional(Type.String()),
      decision_ref: Type.Optional(Type.String()),
    }),
    execute: (p, params) => {
      const updated = setRisk(p, params.id, params);
      return {
        plan: updated,
        message: `Updated risk ${params.id}`,
      };
    },
  });

  // -- Milestone --
  planTool(pi, planRef, {
    name: "koan_add_milestone",
    label: "Add milestone",
    description: "Create new milestone.",
    parameters: Type.Object({
      name: Type.String(),
      files: Type.Optional(Type.Array(Type.String())),
      flags: Type.Optional(Type.Array(Type.String())),
      requirements: Type.Optional(Type.Array(Type.String())),
      acceptance_criteria: Type.Optional(Type.Array(Type.String())),
      tests: Type.Optional(Type.Array(Type.String())),
    }),
    execute: (p, params) => {
      const r = addMilestone(p, params);
      return {
        plan: r.plan,
        message: `Added milestone ${r.id}: "${params.name}"`,
      };
    },
  });

  planTool(pi, planRef, {
    name: "koan_set_milestone_name",
    label: "Set milestone name",
    description: "Update milestone name.",
    parameters: Type.Object({
      id: Type.String(),
      name: Type.String(),
    }),
    execute: (p, params) => {
      const updated = setMilestoneName(p, params.id, params.name);
      return {
        plan: updated,
        message: `Set name for milestone ${params.id}`,
      };
    },
  });

  planTool(pi, planRef, {
    name: "koan_set_milestone_files",
    label: "Set milestone files",
    description: "Update milestone files list.",
    parameters: Type.Object({
      id: Type.String(),
      files: Type.Array(Type.String()),
    }),
    execute: (p, params) => {
      const updated = setMilestoneFiles(p, params.id, params.files);
      return {
        plan: updated,
        message: `Set files for milestone ${params.id} (${params.files.length} files)`,
      };
    },
  });

  planTool(pi, planRef, {
    name: "koan_set_milestone_flags",
    label: "Set milestone flags",
    description: "Update milestone flags list.",
    parameters: Type.Object({
      id: Type.String(),
      flags: Type.Array(Type.String()),
    }),
    execute: (p, params) => {
      const updated = setMilestoneFlags(p, params.id, params.flags);
      return {
        plan: updated,
        message: `Set flags for milestone ${params.id}`,
      };
    },
  });

  planTool(pi, planRef, {
    name: "koan_set_milestone_requirements",
    label: "Set milestone requirements",
    description: "Update milestone requirements list.",
    parameters: Type.Object({
      id: Type.String(),
      requirements: Type.Array(Type.String()),
    }),
    execute: (p, params) => {
      const updated = setMilestoneRequirements(p, params.id, params.requirements);
      return {
        plan: updated,
        message: `Set requirements for milestone ${params.id} (${params.requirements.length} items)`,
      };
    },
  });

  planTool(pi, planRef, {
    name: "koan_set_milestone_acceptance_criteria",
    label: "Set milestone acceptance criteria",
    description: "Update milestone acceptance criteria list.",
    parameters: Type.Object({
      id: Type.String(),
      acceptance_criteria: Type.Array(Type.String()),
    }),
    execute: (p, params) => {
      const updated = setMilestoneAcceptanceCriteria(
        p,
        params.id,
        params.acceptance_criteria,
      );
      return {
        plan: updated,
        message: `Set acceptance criteria for milestone ${params.id} (${params.acceptance_criteria.length} items)`,
      };
    },
  });

  planTool(pi, planRef, {
    name: "koan_set_milestone_tests",
    label: "Set milestone tests",
    description: "Update milestone tests list.",
    parameters: Type.Object({
      id: Type.String(),
      tests: Type.Array(Type.String()),
    }),
    execute: (p, params) => {
      const updated = setMilestoneTests(p, params.id, params.tests);
      return {
        plan: updated,
        message: `Set tests for milestone ${params.id} (${params.tests.length} tests)`,
      };
    },
  });

  // -- CodeIntent --
  planTool(pi, planRef, {
    name: "koan_add_intent",
    label: "Add code intent",
    description: "Add code intent to milestone.",
    parameters: Type.Object({
      milestone: Type.String(),
      file: Type.String(),
      function: Type.Optional(Type.String()),
      behavior: Type.String(),
      decision_refs: Type.Optional(Type.Array(Type.String())),
    }),
    execute: (p, params) => {
      const r = addIntent(p, params);
      return {
        plan: r.plan,
        message: `Added intent ${r.id} to milestone ${params.milestone}`,
      };
    },
  });

  planTool(pi, planRef, {
    name: "koan_set_intent",
    label: "Update code intent",
    description: "Update existing code intent by ID.",
    parameters: Type.Object({
      id: Type.String(),
      file: Type.Optional(Type.String()),
      function: Type.Optional(Type.String()),
      behavior: Type.Optional(Type.String()),
      decision_refs: Type.Optional(Type.Array(Type.String())),
    }),
    execute: (p, params) => {
      const updated = setIntent(p, params.id, params);
      return {
        plan: updated,
        message: `Updated intent ${params.id}`,
      };
    },
  });

  // -- CodeChange --
  planTool(pi, planRef, {
    name: "koan_add_change",
    label: "Add code change",
    description: "Add code change to milestone.",
    parameters: Type.Object({
      milestone: Type.String(),
      file: Type.String(),
      intent_ref: Type.Optional(Type.String()),
      diff: Type.Optional(Type.String()),
      doc_diff: Type.Optional(Type.String()),
      comments: Type.Optional(Type.String()),
    }),
    execute: (p, params) => {
      const r = addChange(p, params);
      return {
        plan: r.plan,
        message: `Added change ${r.id} to milestone ${params.milestone}`,
      };
    },
  });

  planTool(pi, planRef, {
    name: "koan_set_change_diff",
    label: "Set code change diff",
    description: "Update change diff.",
    parameters: Type.Object({
      id: Type.String(),
      diff: Type.String(),
    }),
    execute: (p, params) => {
      const updated = setChangeDiff(p, params.id, params.diff);
      return {
        plan: updated,
        message: `Set diff for change ${params.id}`,
      };
    },
  });

  planTool(pi, planRef, {
    name: "koan_set_change_doc_diff",
    label: "Set code change doc_diff",
    description: "Update change doc_diff.",
    parameters: Type.Object({
      id: Type.String(),
      doc_diff: Type.String(),
    }),
    execute: (p, params) => {
      const updated = setChangeDocDiff(p, params.id, params.doc_diff);
      return {
        plan: updated,
        message: `Set doc_diff for change ${params.id}`,
      };
    },
  });

  planTool(pi, planRef, {
    name: "koan_set_change_comments",
    label: "Set code change comments",
    description: "Update change comments.",
    parameters: Type.Object({
      id: Type.String(),
      comments: Type.String(),
    }),
    execute: (p, params) => {
      const updated = setChangeComments(p, params.id, params.comments);
      return {
        plan: updated,
        message: `Set comments for change ${params.id}`,
      };
    },
  });

  planTool(pi, planRef, {
    name: "koan_set_change_file",
    label: "Set code change file",
    description: "Update change file path.",
    parameters: Type.Object({
      id: Type.String(),
      file: Type.String(),
    }),
    execute: (p, params) => {
      const updated = setChangeFile(p, params.id, params.file);
      return {
        plan: updated,
        message: `Set file for change ${params.id}`,
      };
    },
  });

  planTool(pi, planRef, {
    name: "koan_set_change_intent_ref",
    label: "Set code change intent_ref",
    description: "Update change intent reference.",
    parameters: Type.Object({
      id: Type.String(),
      intent_ref: Type.String(),
    }),
    execute: (p, params) => {
      const updated = setChangeIntentRef(p, params.id, params.intent_ref);
      return {
        plan: updated,
        message: `Set intent_ref for change ${params.id}`,
      };
    },
  });

  // -- Wave --
  planTool(pi, planRef, {
    name: "koan_add_wave",
    label: "Add wave",
    description: "Create wave with milestone list.",
    parameters: Type.Object({
      milestones: Type.Array(Type.String()),
    }),
    execute: (p, params) => {
      const r = addWave(p, params);
      return {
        plan: r.plan,
        message: `Added wave ${r.id} with ${params.milestones.length} milestones`,
      };
    },
  });

  planTool(pi, planRef, {
    name: "koan_set_wave_milestones",
    label: "Set wave milestones",
    description: "Update wave milestones list.",
    parameters: Type.Object({
      id: Type.String(),
      milestones: Type.Array(Type.String()),
    }),
    execute: (p, params) => {
      const updated = setWaveMilestones(p, params.id, params.milestones);
      return {
        plan: updated,
        message: `Set milestones for wave ${params.id}`,
      };
    },
  });

  // -- Diagram --
  planTool(pi, planRef, {
    name: "koan_add_diagram",
    label: "Add diagram",
    description: "Create diagram graph.",
    parameters: Type.Object({
      type: Type.Union([
        Type.Literal("architecture"),
        Type.Literal("state"),
        Type.Literal("sequence"),
        Type.Literal("dataflow"),
      ]),
      scope: Type.String(),
      title: Type.String(),
    }),
    execute: (p, params) => {
      const r = addDiagram(p, params);
      return {
        plan: r.plan,
        message: `Added diagram ${r.id}: "${params.title}"`,
      };
    },
  });

  planTool(pi, planRef, {
    name: "koan_set_diagram",
    label: "Update diagram",
    description: "Update diagram properties.",
    parameters: Type.Object({
      id: Type.String(),
      title: Type.Optional(Type.String()),
      scope: Type.Optional(Type.String()),
      ascii_render: Type.Optional(Type.String()),
    }),
    execute: (p, params) => {
      const updated = setDiagram(p, params.id, params);
      return {
        plan: updated,
        message: `Updated diagram ${params.id}`,
      };
    },
  });

  planTool(pi, planRef, {
    name: "koan_add_diagram_node",
    label: "Add diagram node",
    description: "Add node to diagram.",
    parameters: Type.Object({
      diagram_id: Type.String(),
      id: Type.String(),
      label: Type.String(),
      type: Type.Optional(Type.String()),
    }),
    execute: (p, params) => {
      const updated = addDiagramNode(p, params.diagram_id, params);
      return {
        plan: updated,
        message: `Added node ${params.id} to diagram ${params.diagram_id}`,
      };
    },
  });

  planTool(pi, planRef, {
    name: "koan_add_diagram_edge",
    label: "Add diagram edge",
    description: "Add edge to diagram.",
    parameters: Type.Object({
      diagram_id: Type.String(),
      source: Type.String(),
      target: Type.String(),
      label: Type.String(),
      protocol: Type.Optional(Type.String()),
    }),
    execute: (p, params) => {
      const updated = addDiagramEdge(p, params.diagram_id, params);
      return {
        plan: updated,
        message: `Added edge ${params.source}->${params.target} to diagram ${params.diagram_id}`,
      };
    },
  });

  // -- ReadmeEntry --
  planTool(pi, planRef, {
    name: "koan_set_readme_entry",
    label: "Set readme entry",
    description: "Upsert readme entry by path.",
    parameters: Type.Object({
      path: Type.String(),
      content: Type.String(),
    }),
    execute: (p, params) => {
      const updated = setReadmeEntry(p, params.path, params.content);
      return {
        plan: updated,
        message: `Set readme entry for ${params.path}`,
      };
    },
  });
}
