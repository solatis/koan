import { promises as fs } from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

import type { ExtensionAPI, ExtensionCommandContext, ExtensionContext } from "@mariozechner/pi-coding-agent";

import { ContextCapturePhase } from "./phases/context-capture.js";
import { createInitialState, initializePlanState, type WorkflowState } from "./state.js";
import { createPlanInfo } from "../utils/plan.js";
import { spawnArchitect } from "./subagent.js";
import { createLogger } from "../utils/logger.js";
import { createSubagentDir, readSubagentState } from "../utils/progress.js";
import type { WorkflowDispatch, PlanRef } from "./tools/dispatch.js";

interface Session {
  plan(args: string, ctx: ExtensionCommandContext): Promise<void>;
  execute(_ctx: ExtensionCommandContext): Promise<void>;
  status(ctx: ExtensionCommandContext): Promise<void>;
}

export function createSession(pi: ExtensionAPI, dispatch: WorkflowDispatch, planRef: PlanRef): Session {
  const state: WorkflowState = createInitialState();
  const log = createLogger("Session");

  // Completion callback for context-capture phase. Runs inside the
  // koan_store_context tool call -- the tool blocks until the architect
  // subagent finishes. The LLM sees context capture + architect outcome
  // in one tool response. No agent_end polling needed.
  const onContextComplete = async (ctx: ExtensionContext): Promise<string> => {
    if (!state.plan) {
      return "Context captured but no plan state available.";
    }

    const planDir = state.plan.directory;
    const planJsonPath = path.join(planDir, "plan.json");
    const subagentDir = await createSubagentDir(planDir, "architect");

    state.phase = "architect-running";
    ctx.ui.notify("Launching architect subagent for plan-design...", "info");
    log("Spawning architect after context capture", { planDir, subagentDir });

    const extensionPath = path.resolve(import.meta.dirname, "../../extensions/koan.ts");

    const pollInterval = setInterval(async () => {
      const s = await readSubagentState(subagentDir);
      if (s?.current) {
        ctx.ui.notify(`Architect: ${s.current}`, "info");
      }
    }, 2000);

    const result = await spawnArchitect({
      planDir,
      subagentDir,
      cwd: ctx.cwd,
      extensionPath,
      log,
    });

    clearInterval(pollInterval);

    if (result.exitCode !== 0) {
      state.phase = "architect-failed";
      const detail = result.stderr.slice(0, 500);
      log("Architect subagent failed", { exitCode: result.exitCode, stderr: detail });
      ctx.ui.notify(`Architect subagent failed (exit ${result.exitCode}).`, "error");
      return `Context captured. Architect subagent failed (exit ${result.exitCode}).\n\nStderr:\n${detail}`;
    }

    let planExists = false;
    try {
      await fs.access(planJsonPath);
      planExists = true;
    } catch {
      // plan.json not written
    }

    if (!planExists) {
      state.phase = "architect-failed";
      log("Architect completed but plan.json not found", { planJsonPath });
      ctx.ui.notify("Architect completed but plan.json was not written.", "error");
      return "Context captured. Architect completed but plan.json was not written.";
    }

    state.phase = "plan-design-complete";
    log("Architect plan-design complete", { planDir });
    ctx.ui.notify("Plan-design phase complete.", "success");
    return `Context captured. Plan written to ${planDir}/plan.json.`;
  };

  const contextPhase = new ContextCapturePhase(pi, state, dispatch, createLogger("Context"), onContextComplete);

  return {
    async plan(args, ctx) {
      const description = args.trim();
      if (!description) {
        ctx.ui.notify("Usage: /koan plan <task description>", "error");
        return;
      }

      if (state.phase === "context" && state.context?.active) {
        ctx.ui.notify("Context capture already running. Use /koan status to check progress.", "warning");
        return;
      }

      await ctx.waitForIdle();

      const planInfo = await createPlanInfo(description, ctx.cwd);
      initializePlanState(state, planInfo, description);
      planRef.dir = planInfo.directory;

      log("Plan command invoked", {
        cwd: ctx.cwd,
        description,
        planId: planInfo.id,
        planDirectory: planInfo.directory,
      });

      await contextPhase.begin(description, planInfo, ctx);
    },

    async execute(ctx) {
      ctx.ui.notify("Execution mode is not yet implemented.", "warning");
    },

    async status(ctx) {
      const summary = buildStatusSummary(state, ctx.cwd);
      ctx.ui.notify(summary, "info");
    },
  };
}

function buildStatusSummary(state: WorkflowState, cwd: string): string {
  const lines: string[] = [];
  const plan = state.plan;

  if (plan) {
    lines.push(`Plan ${plan.id}`);
    lines.push(`Directory: ${formatPath(plan.directory, cwd)}`);
  } else {
    lines.push("No active plan.");
  }

  switch (state.phase) {
    case "idle":
      lines.push("Koan planner is idle.");
      break;
    case "context": {
      const attempt = state.context?.attempt ?? 0;
      lines.push(`Context capture in progress (attempt ${attempt}).`);
      if (state.context?.contextFilePath) {
        lines.push(`Target: ${formatPath(state.context.contextFilePath, cwd)}`);
      }
      break;
    }
    case "context-complete":
      lines.push("Context captured successfully.");
      if (state.context?.contextFilePath) {
        lines.push(`Stored at: ${formatPath(state.context.contextFilePath, cwd)}`);
      }
      break;
    case "context-failed":
      lines.push("Context capture failed. Re-run /koan plan to try again.");
      break;
    case "architect-running":
      lines.push("Architect subagent running (plan-design phase)...");
      break;
    case "architect-failed":
      lines.push("Architect subagent failed. Check plan directory for details.");
      break;
    case "plan-design-complete":
      lines.push("Plan-design phase complete.");
      if (plan) {
        lines.push(`Plan: ${formatPath(path.join(plan.directory, "plan.json"), cwd)}`);
      }
      break;
    default:
      lines.push("Unknown planner state.");
      break;
  }

  return lines.join("\n");
}

function formatPath(target: string, cwd: string): string {
  const home = os.homedir();
  if (target.startsWith(home)) {
    return `~${target.slice(home.length)}`;
  }

  const relative = path.relative(cwd, target);
  if (!relative.startsWith("..")) {
    return relative;
  }

  return target;
}
