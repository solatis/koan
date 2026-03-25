// Entry point for the koan pi extension. Serves dual roles:
//
//   Parent session mode — registers the koan_plan tool and /koan commands.
//   Subagent mode       — reads task.json from --koan-dir, dispatches to
//                         the appropriate phase workflow.
//
// All tools register unconditionally at init; phases restrict access at
// runtime via the tool_call permission fence in BasePhase.
//
// RuntimeContext is a mutable carrier set once during before_agent_start.
// Tools register at init (before flags are available) and read ctx at
// call time — the mutable-ref pattern decouples static registration from
// dynamic phase routing.

import * as path from "node:path";
import { Type } from "@sinclair/typebox";
import type { ExtensionAPI, ExtensionContext } from "@mariozechner/pi-coding-agent";

import { dispatchPhase } from "../src/planner/phases/dispatch.js";
import { registerAllTools, createRuntimeContext } from "../src/planner/tools/index.js";
import { createLogger, setLogDir } from "../src/utils/logger.js";
import { EventLog, extractToolCall, extractToolResult } from "../src/planner/lib/audit.js";
import { readTaskFile } from "../src/planner/lib/task.js";
import { openKoanConfig } from "../src/planner/ui/config/menu.js";
import { createEpicDirectory } from "../src/planner/epic/state.js";
import { exportConversation } from "../src/planner/conversation.js";
import { runPipeline } from "../src/planner/driver.js";
import { startWebServer, openBrowser } from "../src/planner/web/server.js";
import { registerTruncationOverride } from "../src/planner/lib/truncation-override.js";

function currentModelId(ctx: ExtensionContext): string | null {
  const model = ctx.model;
  if (!model) return null;
  return `${model.provider}/${model.id}`;
}

/**
 * Registers infrastructure-level event handlers that must be in place before
 * `before_agent_start` fires.
 *
 * **Ordering contract:** call immediately after `registerAllTools` and before
 * the `before_agent_start` dispatch guard. The audit system's `tool_result`
 * handler is registered inside `before_agent_start`; the truncation override
 * installed here must precede it so the audit handler observes the original
 * event rather than the replacement content we return. Placing this call
 * structurally before `before_agent_start` makes the constraint positional
 * rather than implicit.
 */
function registerInfrastructureHandlers(pi: ExtensionAPI): void {
  registerTruncationOverride(pi);
}

export default function koan(pi: ExtensionAPI): void {
  const log = createLogger("Koan");

  // Single flag: the subagent directory path. The child reads task.json from
  // this directory to discover its role and task parameters — no structured
  // data flows through CLI flags.
  pi.registerFlag("koan-dir", {
    description: "Subagent working directory (internal — set by parent before spawn)",
    type: "string",
    default: "",
  });

  pi.registerFlag("koan-webserver-port", {
    description: "Fixed port for the koan web server (default: random)",
    type: "string",
    default: "",
  });

  pi.registerFlag("koan-webserver-token", {
    description: "Fixed session token (UUID) for the koan web server (default: random)",
    type: "string",
    default: "",
  });

  const ctx = createRuntimeContext();

  registerAllTools(pi, ctx);
  registerInfrastructureHandlers(pi);

  // Dispatch happens exactly once per session (guard prevents re-entry on
  // subsequent before_agent_start calls, which pi may emit on reconnect).
  let dispatched = false;
  pi.on("before_agent_start", async (_event, extCtx) => {
    if (dispatched) return;
    dispatched = true;

    const dirFlag = pi.getFlag("koan-dir");
    if (!dirFlag || typeof dirFlag !== "string" || dirFlag.trim().length === 0) {
      // No --koan-dir flag: running as parent session, not as a subagent.
      return;
    }

    const subagentDir = dirFlag.trim();

    // task.json was written by the parent before spawning this process.
    // Throws if missing or malformed — that is a programming error, not a user error.
    const task = await readTaskFile(subagentDir);

    ctx.epicDir = task.epicDir;
    ctx.subagentDir = subagentDir;
    // Thread phaseInstructions from the workflow orchestrator's decision into context.
    // Present only when the user provided focus instructions during the workflow
    // decision interaction. Phases access this via this.ctx.phaseInstructions in
    // their getStepGuidance() implementation.
    ctx.phaseInstructions = task.phaseInstructions;

    const eventLog = new EventLog(
      subagentDir,
      task.role,
      task.role,
      currentModelId(extCtx),
    );
    await eventLog.open();

    // Make the event log available to tools via ctx.
    ctx.eventLog = eventLog;

    pi.on("tool_call", (event) => {
      void eventLog.append(extractToolCall(event as {
        toolCallId: string;
        toolName: string;
        input: Record<string, unknown>;
      }));
    });

    pi.on("tool_result", (event) => {
      void eventLog.append(extractToolResult(event as {
        toolCallId: string;
        toolName: string;
        input: Record<string, unknown>;
        content: Array<{ type: string; text?: string }>;
        isError: boolean;
      }));
    });

    pi.on("turn_end", (event) => {
      const msg = event.message as {
        role: string;
        usage?: { input: number; output: number; cacheRead: number; cacheWrite: number };
        content?: Array<{ type: string; thinking?: string }>;
      };
      if (msg.role === "assistant" && msg.usage) {
        void eventLog.append({
          kind: "usage",
          input: msg.usage.input,
          output: msg.usage.output,
          cacheRead: msg.usage.cacheRead,
          cacheWrite: msg.usage.cacheWrite,
        });
      }
      if (msg.role === "assistant" && Array.isArray(msg.content)) {
        for (const block of msg.content) {
          if (block.type === "thinking" && typeof block.thinking === "string" && block.thinking.length > 0) {
            void eventLog.append({
              kind: "thinking",
              text: block.thinking,
              chars: block.thinking.length,
            });
          }
        }
      }
    });

    pi.on("session_shutdown", () => {
      void eventLog.close();
    });

    await dispatchPhase(pi, task, ctx, log, eventLog);
  });

  // -- koan_plan tool --
  pi.registerTool({
    name: "koan_plan",
    label: "Plan",
    description: [
      "Launch a structured planning pipeline for complex, multi-file tasks.",
      "Invoke when the user asks to plan, use the planner, or when the task",
      "is too large to implement directly.",
      "",
      "The current conversation is automatically captured — it becomes the",
      "planning context. The pipeline spawns specialized agents that decompose",
      "the task into stories and execute them one at a time.",
      "",
      "This is a long-running operation. Do not invoke for simple tasks.",
    ].join("\n"),
    parameters: Type.Object({}),
    async execute(_toolCallId, _params, _signal, _onUpdate, extCtx) {
      const epicInfo = await createEpicDirectory("", extCtx.cwd);
      ctx.epicDir = epicInfo.directory;
      setLogDir(epicInfo.directory);

      const extensionPath = path.resolve(import.meta.dirname, "koan.ts");

      const portFlag = pi.getFlag("koan-webserver-port") as string || "";
      const serverPort = portFlag ? parseInt(portFlag, 10) : 0;
      const serverToken = (pi.getFlag("koan-webserver-token") as string) || "";
      const server = await startWebServer(epicInfo.directory, { port: serverPort, token: serverToken });
      try {
        // Skip opening the browser when a fixed port is set — the caller
        // (e.g. an automated agent or test harness) already knows the URL.
        if (!serverPort) await openBrowser(pi, server.url);
        await exportConversation(extCtx.sessionManager, epicInfo.directory);
        log("Conversation exported", { epicDir: epicInfo.directory });

        const result = await runPipeline(epicInfo.directory, extCtx.cwd, extensionPath, log, server);

        return {
          content: [{ type: "text" as const, text: `Dashboard: ${server.url}\n\n${result.summary}` }],
          details: undefined,
        };
      } finally {
        server.close();
      }
    },
  });

  // -- Commands --
  pi.registerCommand("koan", {
    description: "Koan commands. Usage: /koan config",
    handler: async (args, extCtx) => {
      const subcommand = args.trim();
      if (subcommand === "config") {
        await openKoanConfig(extCtx);
      } else if (subcommand === "") {
        extCtx.ui.notify("Usage: /koan config", "info");
      } else {
        extCtx.ui.notify(`Unknown koan subcommand: "${subcommand}". Usage: /koan config`, "warning");
      }
    },
  });
}
