import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import { PlanDesignPhase } from "./plan-design.js";
import { createLogger, type Logger } from "../../utils/logger.js";
import type { WorkflowDispatch, PlanRef } from "../tools/dispatch.js";

export interface SubagentConfig {
  role: string;
  phase: string;
  planDir: string;
  subagentDir: string;
}

// Detects subagent mode by checking flags set via CLI (pi -p --koan-role
// architect --koan-phase plan-design ...). Flags are unavailable during
// init (getFlag() returns undefined before _buildRuntime()), so this
// must be called from before_agent_start or later.
export function detectSubagentMode(pi: ExtensionAPI): SubagentConfig | null {
  const role = pi.getFlag("koan-role");
  if (!role || typeof role !== "string" || role.trim().length === 0) {
    return null;
  }

  const phase = pi.getFlag("koan-phase");
  const planDir = pi.getFlag("koan-plan-dir");
  const subagentDir = pi.getFlag("koan-subagent-dir");

  return {
    role: role.trim(),
    phase: typeof phase === "string" ? phase.trim() : "",
    planDir: typeof planDir === "string" ? planDir.trim() : "",
    subagentDir: typeof subagentDir === "string" ? subagentDir.trim() : "",
  };
}

export async function dispatchPhase(
  pi: ExtensionAPI,
  config: SubagentConfig,
  dispatch: WorkflowDispatch,
  planRef: PlanRef,
  log?: Logger,
): Promise<void> {
  const logger = log ?? createLogger("Dispatch");

  if (config.role === "architect" && config.phase === "plan-design") {
    logger("Dispatching to plan-design workflow", { planDir: config.planDir });
    const phase = new PlanDesignPhase(
      pi,
      {
        planDir: config.planDir,
        subagentDir: config.subagentDir || undefined,
      },
      dispatch,
      planRef,
      logger,
    );
    await phase.begin();
    return;
  }

  logger("Unknown role/phase combination", { role: config.role, phase: config.phase });
}
