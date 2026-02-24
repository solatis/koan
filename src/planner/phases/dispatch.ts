// Phase dispatch: detects subagent mode from CLI flags and routes to the
// appropriate phase constructor. Flags are unavailable at extension init
// (getFlag returns undefined before _buildRuntime), so detection is
// deferred to before_agent_start.

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import { PlanDesignPhase } from "./plan-design/phase.js";
import { QRDecomposePhase } from "./qr-decompose/phase.js";
import { QRVerifyPhase } from "./qr-verify/phase.js";
import { createLogger, type Logger } from "../../utils/logger.js";
import type { WorkflowDispatch, PlanRef } from "../lib/dispatch.js";
import type { EventLog } from "../lib/audit.js";

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
  eventLog?: EventLog,
): Promise<void> {
  const logger = log ?? createLogger("Dispatch");

  if (config.role === "architect" && config.phase === "plan-design") {
    logger("Dispatching to plan-design workflow", { planDir: config.planDir });
    const phase = new PlanDesignPhase(
      pi,
      { planDir: config.planDir },
      dispatch,
      planRef,
      logger,
      eventLog,
    );
    await phase.begin();
    return;
  }

  if (config.role === "qr-decomposer" && config.phase === "qr-plan-design") {
    logger("Dispatching to qr-decompose workflow", { planDir: config.planDir });
    const phase = new QRDecomposePhase(
      pi,
      { planDir: config.planDir },
      dispatch,
      planRef,
      logger,
      eventLog,
    );
    await phase.begin();
    return;
  }

  if (config.role === "reviewer" && config.phase === "qr-plan-design") {
    const itemId = pi.getFlag("koan-qr-item") as string;
    if (!itemId) {
      logger("Reviewer missing --koan-qr-item flag");
      return;
    }
    logger("Dispatching to qr-verify workflow", { planDir: config.planDir, itemId });
    const phase = new QRVerifyPhase(
      pi,
      { planDir: config.planDir, itemId },
      dispatch,
      planRef,
      logger,
      eventLog,
    );
    await phase.begin();
    return;
  }

  logger("Unknown role/phase combination", { role: config.role, phase: config.phase });
}
