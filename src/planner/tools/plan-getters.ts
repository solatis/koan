import { Type } from "@sinclair/typebox";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import type { PlanRef } from "./dispatch.js";
import { loadPlan } from "../plan/serialize.js";
import type { Plan, Milestone, CodeIntent, CodeChange } from "../plan/types.js";

export function registerPlanGetterTools(
  pi: ExtensionAPI,
  planRef: PlanRef,
): void {
  pi.registerTool({
    name: "koan_get_plan",
    label: "Get plan summary",
    description:
      "Returns plan overview and entity counts with IDs for drill-down.",
    parameters: Type.Object({}),
    async execute() {
      if (!planRef.dir) throw new Error("No plan directory is active.");
      const p = await loadPlan(planRef.dir);
      const summary = formatPlanSummary(p);
      return {
        content: [{ type: "text" as const, text: summary }],
        details: undefined,
      };
    },
  });

  pi.registerTool({
    name: "koan_get_milestone",
    label: "Get milestone by ID",
    description: "Returns full milestone with code_intents and code_changes.",
    parameters: Type.Object({
      id: Type.String({ description: "Milestone ID (e.g., M-001)" }),
    }),
    async execute(_toolCallId, params) {
      if (!planRef.dir) throw new Error("No plan directory is active.");
      const p = await loadPlan(planRef.dir);
      const m = p.milestones.find((x) => x.id === params.id);
      if (!m) throw new Error(`Milestone ${params.id} not found`);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(m, null, 2) }],
        details: undefined,
      };
    },
  });

  pi.registerTool({
    name: "koan_get_decision",
    label: "Get decision by ID",
    description: "Returns decision from decision log.",
    parameters: Type.Object({
      id: Type.String({ description: "Decision ID (e.g., DL-001)" }),
    }),
    async execute(_toolCallId, params) {
      if (!planRef.dir) throw new Error("No plan directory is active.");
      const p = await loadPlan(planRef.dir);
      const d = p.planning_context.decision_log.find(
        (x) => x.id === params.id,
      );
      if (!d) throw new Error(`Decision ${params.id} not found`);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(d, null, 2) }],
        details: undefined,
      };
    },
  });

  pi.registerTool({
    name: "koan_get_intent",
    label: "Get code intent by ID",
    description: "Returns code intent and parent milestone ID.",
    parameters: Type.Object({
      id: Type.String({ description: "Intent ID (e.g., CI-M-001-001)" }),
    }),
    async execute(_toolCallId, params) {
      if (!planRef.dir) throw new Error("No plan directory is active.");
      const p = await loadPlan(planRef.dir);
      const result = findIntent(p, params.id);
      if (!result)
        throw new Error(`Intent ${params.id} not found`);
      return {
        content: [
          {
            type: "text" as const,
            text: JSON.stringify(
              { milestone_id: result.milestoneId, intent: result.intent },
              null,
              2,
            ),
          },
        ],
        details: undefined,
      };
    },
  });

  pi.registerTool({
    name: "koan_get_change",
    label: "Get code change by ID",
    description: "Returns code change and parent milestone ID.",
    parameters: Type.Object({
      id: Type.String({ description: "Change ID (e.g., CC-M-001-001)" }),
    }),
    async execute(_toolCallId, params) {
      if (!planRef.dir) throw new Error("No plan directory is active.");
      const p = await loadPlan(planRef.dir);
      const result = findChange(p, params.id);
      if (!result)
        throw new Error(`Change ${params.id} not found`);
      return {
        content: [
          {
            type: "text" as const,
            text: JSON.stringify(
              { milestone_id: result.milestoneId, change: result.change },
              null,
              2,
            ),
          },
        ],
        details: undefined,
      };
    },
  });
}

function formatPlanSummary(p: Plan): string {
  const lines = [
    "Plan Summary",
    "============",
    "",
    "Overview:",
    `  Problem: ${p.overview.problem || "(empty)"}`,
    `  Approach: ${p.overview.approach || "(empty)"}`,
    "",
    `Milestones (${p.milestones.length}):`,
    ...p.milestones.map((m) => `  ${m.id}: ${m.name}`),
    "",
    `Decisions (${p.planning_context.decision_log.length}):`,
    ...p.planning_context.decision_log.map((d) => `  ${d.id}: ${d.decision}`),
    "",
    `Waves (${p.waves.length}):`,
    ...p.waves.map((w) => `  ${w.id}: [${w.milestones.join(", ")}]`),
    "",
    `Diagrams (${p.diagram_graphs.length}):`,
    ...p.diagram_graphs.map((d) => `  ${d.id}: ${d.title} (${d.type})`),
  ];
  return lines.join("\n");
}

function findIntent(
  p: Plan,
  id: string,
): { milestoneId: string; intent: CodeIntent } | null {
  for (const m of p.milestones) {
    const intent = m.code_intents.find((ci) => ci.id === id);
    if (intent) return { milestoneId: m.id, intent };
  }
  return null;
}

function findChange(
  p: Plan,
  id: string,
): { milestoneId: string; change: CodeChange } | null {
  for (const m of p.milestones) {
    const change = m.code_changes.find((cc) => cc.id === id);
    if (change) return { milestoneId: m.id, change };
  }
  return null;
}
