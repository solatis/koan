// Phase dispatch: detects subagent mode from CLI flags and routes to the
// appropriate phase constructor. Flags are unavailable at extension init
// (getFlag returns undefined before _buildRuntime), so detection is
// deferred to before_agent_start.

import { promises as fs } from "node:fs";
import * as path from "node:path";

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import { PlanDesignPhase } from "./plan-design/phase.js";
import { PlanDesignFixPhase } from "./plan-design/fix-phase.js";
import { QRDecomposePhase } from "./qr-decompose/phase.js";
import { QRVerifyPhase } from "./qr-verify/phase.js";
import { createLogger, type Logger } from "../../utils/logger.js";
import type { WorkflowDispatch, PlanRef } from "../lib/dispatch.js";
import type { EventLog } from "../lib/audit.js";
import type { QRFile } from "../qr/types.js";

export interface SubagentConfig {
  role: string;
  phase: string;
  planDir: string;
  subagentDir: string;
  fix: string | null; // QR phase being fixed, null when initial mode
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

  const fix = pi.getFlag("koan-fix");

  return {
    role: role.trim(),
    phase: typeof phase === "string" ? phase.trim() : "",
    planDir: typeof planDir === "string" ? planDir.trim() : "",
    subagentDir: typeof subagentDir === "string" ? subagentDir.trim() : "",
    fix: typeof fix === "string" && fix.trim().length > 0 ? fix.trim() : null,
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

  if (config.role === "architect" && config.fix === "plan-design") {
    // Dispatch reads the QR file here, not in session.ts.
    // The fix architect runs as a separate process with only the plan
    // directory path -- it cannot receive in-memory QR data from the
    // parent session. Reading from disk at dispatch boundary is the
    // only clean handoff point.
    const qrPath = path.join(config.planDir, "qr-plan-design.json");
    let qrFile: QRFile;
    try {
      const raw = await fs.readFile(qrPath, "utf8");
      qrFile = JSON.parse(raw) as QRFile;
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      logger("Fix dispatch: failed to read QR file", { error: msg });
      return;
    }
    const failures = qrFile.items.filter((i) => i.status === "FAIL");
    if (failures.length === 0) {
      logger("Fix dispatch: no FAIL items in QR file, skipping fix phase");
      return;
    }
    logger("Dispatching to plan-design fix workflow", {
      planDir: config.planDir,
      failureCount: failures.length,
    });
    const phase = new PlanDesignFixPhase(
      pi,
      { planDir: config.planDir, failures },
      dispatch,
      planRef,
      logger,
      eventLog,
    );
    await phase.begin();
    return;
  }

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
