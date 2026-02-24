// Entry point for the koan pi extension. Serves dual roles: parent session
// (registers /koan command) and subagent mode (dispatches to phase workflow
// via CLI flags). All tools register unconditionally at init; phases restrict
// access via tool_call blocking at runtime.

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import { createSession } from "../src/planner/session.js";
import { detectSubagentMode, dispatchPhase } from "../src/planner/phases/dispatch.js";
import { registerAllTools, createDispatch, createPlanRef } from "../src/planner/tools/index.js";
import { createLogger } from "../src/utils/logger.js";
import { EventLog, extractToolEvent } from "../src/planner/lib/audit.js";

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

  pi.registerFlag("koan-qr-item", {
    description: "QR item ID for reviewer subagent",
    type: "string",
    default: "",
  });

  // Pi snapshots tools during _buildRuntime() at init. All 44 tools
  // register here unconditionally. Phases restrict access via tool_call
  // blocking at runtime.
  const dispatch = createDispatch();
  const planRef = createPlanRef();

  registerAllTools(pi, planRef, dispatch);

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

      // EventLog exists only in subagent mode. Parent mode has no audit log.
      let eventLog: EventLog | undefined;
      if (config.subagentDir) {
        eventLog = new EventLog(config.subagentDir, config.role, config.phase);
        await eventLog.open();

        // Capture all tool results for the audit trail. Graduated detail:
        // file paths for read/edit/write, binary name for bash, full
        // input+response for koan_* tools, name-only for everything else.
        pi.on("tool_result", (event) => {
          void eventLog!.append(extractToolEvent(event as {
            toolName: string;
            input: Record<string, unknown>;
            content: Array<{ type: string; text?: string }>;
            isError: boolean;
          }));
        });

        pi.on("session_shutdown", () => {
          void eventLog!.close();
        });
      }

      await dispatchPhase(pi, config, dispatch, planRef, log, eventLog);
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
