import { Type } from "@sinclair/typebox";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import type { PlanRef } from "./dispatch.js";
import { loadPlan, savePlan } from "../plan/serialize.js";
import {
  setOverview,
  setConstraints,
  setInvisibleKnowledge,
} from "../plan/mutate.js";

export function registerPlanSetterTools(
  pi: ExtensionAPI,
  planRef: PlanRef,
): void {
  pi.registerTool({
    name: "koan_set_overview",
    label: "Set plan overview",
    description: "Set problem statement and approach.",
    parameters: Type.Object({
      problem: Type.Optional(Type.String()),
      approach: Type.Optional(Type.String()),
    }),
    async execute(_toolCallId, params) {
      if (!planRef.dir) throw new Error("No plan directory is active.");
      const p = await loadPlan(planRef.dir);
      const updated = setOverview(
        p,
        params as { problem?: string; approach?: string },
      );
      await savePlan(updated, planRef.dir);
      return {
        content: [{ type: "text" as const, text: "Overview updated." }],
      };
    },
  });

  pi.registerTool({
    name: "koan_set_constraints",
    label: "Set plan constraints",
    description: "Set planning constraints list.",
    parameters: Type.Object({
      constraints: Type.Array(Type.String()),
    }),
    async execute(_toolCallId, params) {
      if (!planRef.dir) throw new Error("No plan directory is active.");
      const p = await loadPlan(planRef.dir);
      const updated = setConstraints(
        p,
        (params as { constraints: string[] }).constraints,
      );
      await savePlan(updated, planRef.dir);
      return {
        content: [
          {
            type: "text" as const,
            text: `Constraints set (${(params as { constraints: string[] }).constraints.length} items).`,
          },
        ],
      };
    },
  });

  pi.registerTool({
    name: "koan_set_invisible_knowledge",
    label: "Set invisible knowledge",
    description: "Set system description, invariants, and tradeoffs.",
    parameters: Type.Object({
      system: Type.Optional(Type.String()),
      invariants: Type.Optional(Type.Array(Type.String())),
      tradeoffs: Type.Optional(Type.Array(Type.String())),
    }),
    async execute(_toolCallId, params) {
      if (!planRef.dir) throw new Error("No plan directory is active.");
      const p = await loadPlan(planRef.dir);
      const updated = setInvisibleKnowledge(
        p,
        params as {
          system?: string;
          invariants?: string[];
          tradeoffs?: string[];
        },
      );
      await savePlan(updated, planRef.dir);
      return {
        content: [
          { type: "text" as const, text: "Invisible knowledge updated." },
        ],
      };
    },
  });
}
