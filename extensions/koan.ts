import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import { createSession } from "../src/planner/session.js";
import { detectSubagentMode, dispatchPhase } from "../src/planner/phases/dispatch.js";
import { createDispatch, registerWorkflowTools, createPlanRef } from "../src/planner/tools/dispatch.js";
import { registerPlanGetterTools } from "../src/planner/tools/plan-getters.js";
import { registerPlanSetterTools } from "../src/planner/tools/plan-setters.js";
import { registerPlanEntityTools } from "../src/planner/tools/plan-entities.js";
import { registerQRTools } from "../src/planner/tools/qr-tools.js";
import { createLogger } from "../src/utils/logger.js";

export default function koan(pi: ExtensionAPI): void {
  const log = createLogger("Koan");

  pi.registerFlag("koan-role", {
    description: "Koan subagent role (reserved)",
    type: "string",
    default: "",
  });

  pi.registerFlag("koan-phase", {
    description: "Koan workflow phase (reserved)",
    type: "string",
    default: "",
  });

  pi.registerFlag("koan-plan-dir", {
    description: "Koan plan directory path",
    type: "string",
    default: "",
  });

  pi.registerFlag("koan-subagent-dir", {
    description: "Koan subagent working directory",
    type: "string",
    default: "",
  });

  // Pi snapshots tools during _buildRuntime() at init. All 44 tools
  // register here unconditionally. Phases restrict access via tool_call
  // blocking at runtime.
  const dispatch = createDispatch();
  const planRef = createPlanRef();

  registerWorkflowTools(pi, dispatch);
  registerPlanGetterTools(pi, planRef);
  registerPlanSetterTools(pi, planRef);
  registerPlanEntityTools(pi, planRef);
  registerQRTools(pi, planRef);

  // Subagent detection runs at before_agent_start (flags
  // are unavailable during init).
  let dispatched = false;
  pi.on("before_agent_start", async () => {
    if (dispatched) return;
    dispatched = true;
    const config = detectSubagentMode(pi);
    if (config) {
      const planDir = pi.getFlag("koan-plan-dir") as string;
      if (planDir) {
        planRef.dir = planDir;
      }
      await dispatchPhase(pi, config, dispatch, planRef, log);
    }
  });

  // Session: parent-mode workflow engine.
  const session = createSession(pi, dispatch, planRef);

  pi.registerCommand("koan", {
    description: "Koan planning workflow",
    handler: async (args, ctx) => {
      const [subcommand, ...rest] = args.trim().split(/\s+/);
      const command = subcommand ?? "";
      const remainingArgs = rest.join(" ");

      switch (command) {
        case "plan":
          await session.plan(remainingArgs, ctx);
          break;
        case "execute":
          await session.execute(ctx);
          break;
        case "status":
          await session.status(ctx);
          break;
        default:
          ctx.ui.notify(
            "Usage: /koan plan <task>, /koan execute, or /koan status",
            "error",
          );
          break;
      }
    },
  });
}
