// Phase dispatch: detects subagent mode from CLI flags and routes to the
// appropriate phase constructor. Flags are unavailable at extension init
// (getFlag returns undefined before _buildRuntime), so detection is
// deferred to before_agent_start.

import { promises as fs } from "node:fs";
import * as path from "node:path";

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import { PlanDesignPhase } from "./plan-design/phase.js";
import { PlanDesignFixPhase } from "./plan-design/fix-phase.js";
import { PlanCodePhase } from "./plan-code/phase.js";
import { PlanCodeFixPhase } from "./plan-code/fix-phase.js";
import { PlanDocsPhase } from "./plan-docs/phase.js";
import { PlanDocsFixPhase } from "./plan-docs/fix-phase.js";
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
  fix: string | null;
}

type WorkPhaseKey = "plan-design" | "plan-code" | "plan-docs";

function parseWorkPhase(value: string | null): WorkPhaseKey | null {
  if (value === "plan-design" || value === "plan-code" || value === "plan-docs") {
    return value;
  }
  return null;
}

function parseQRPhase(value: string): WorkPhaseKey | null {
  if (!value.startsWith("qr-")) return null;
  return parseWorkPhase(value.slice(3));
}

async function loadFixFailures(planDir: string, phase: WorkPhaseKey): Promise<QRFile | null> {
  const qrPath = path.join(planDir, `qr-${phase}.json`);
  try {
    const raw = await fs.readFile(qrPath, "utf8");
    return JSON.parse(raw) as QRFile;
  } catch {
    return null;
  }
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

  // -- Fix modes --

  const fixPhase = parseWorkPhase(config.fix);
  if (fixPhase) {
    const qrFile = await loadFixFailures(config.planDir, fixPhase);
    if (!qrFile) {
      logger("Fix dispatch: failed to read QR file", { phase: fixPhase });
      return;
    }

    const failures = qrFile.items.filter((i) => i.status === "FAIL");
    if (failures.length === 0) {
      logger("Fix dispatch: no FAIL items in QR file, skipping fix phase", { phase: fixPhase });
      return;
    }

    if (config.role === "architect" && fixPhase === "plan-design") {
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

    if (config.role === "developer" && fixPhase === "plan-code") {
      const phase = new PlanCodeFixPhase(
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

    if (config.role === "technical-writer" && fixPhase === "plan-docs") {
      const phase = new PlanDocsFixPhase(
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
  }

  // -- Work phases --

  if (config.role === "architect" && config.phase === "plan-design") {
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

  if (config.role === "developer" && config.phase === "plan-code") {
    const phase = new PlanCodePhase(
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

  if (config.role === "technical-writer" && config.phase === "plan-docs") {
    const phase = new PlanDocsPhase(
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

  // -- QR phases --

  const qrWorkPhase = parseQRPhase(config.phase);
  if (config.role === "qr-decomposer" && qrWorkPhase) {
    const phase = new QRDecomposePhase(
      pi,
      { planDir: config.planDir, workPhase: qrWorkPhase },
      dispatch,
      planRef,
      logger,
      eventLog,
    );
    await phase.begin();
    return;
  }

  if (config.role === "reviewer" && qrWorkPhase) {
    const itemId = pi.getFlag("koan-qr-item") as string;
    if (!itemId) {
      logger("Reviewer missing --koan-qr-item flag");
      return;
    }

    const phase = new QRVerifyPhase(
      pi,
      { planDir: config.planDir, itemId, workPhase: qrWorkPhase },
      dispatch,
      planRef,
      logger,
      eventLog,
    );
    await phase.begin();
    return;
  }

  logger("Unknown role/phase combination", {
    role: config.role,
    phase: config.phase,
    fix: config.fix,
  });
}
