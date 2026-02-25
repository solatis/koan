// Parent session: orchestrates the koan workflow (context capture -> architect
// -> QR decompose -> QR verify pool). Polls subagent state.json for progress.
// Widget displays persistent progress; destroyed on completion.

import { promises as fs } from "node:fs";
import * as path from "node:path";

import type { ExtensionAPI, ExtensionCommandContext, ExtensionContext } from "@mariozechner/pi-coding-agent";

import { ContextCapturePhase } from "./phases/context-capture/phase.js";
import { createInitialState, initializePlanState, type WorkflowState } from "./state.js";
import { createPlanInfo } from "../utils/plan.js";
import { spawnArchitect, spawnArchitectFix, spawnQRDecomposer, spawnReviewer } from "./subagent.js";
import { createLogger, setLogDir, type Logger } from "../utils/logger.js";
import { createSubagentDir } from "../utils/progress.js";
import { readProjection, readRecentLogs } from "./lib/audit.js";
import type { WorkflowDispatch, PlanRef } from "./lib/dispatch.js";
import { pool } from "./lib/pool.js";
import type { QRFile } from "./qr/types.js";
import { MAX_FIX_ITERATIONS, qrPassesAtIteration } from "./qr/severity.js";
import { WidgetController } from "./ui/widget.js";

// -- Types --

interface Session {
  plan(args: string, ctx: ExtensionCommandContext): Promise<void>;
  execute(_ctx: ExtensionCommandContext): Promise<void>;
  status(ctx: ExtensionCommandContext): Promise<void>;
}

interface QRBlockResult {
  summary: string;
  passed: boolean;
}

// -- Session --

export function createSession(pi: ExtensionAPI, dispatch: WorkflowDispatch, planRef: PlanRef): Session {
  const state: WorkflowState = createInitialState();
  const log = createLogger("Session");
  let widget: WidgetController | null = null;

  // Completion callback for context-capture phase. Runs inside the
  // koan_store_context tool call -- the tool blocks until the architect
  // subagent finishes. The LLM sees context capture + architect outcome
  // in one tool response.
  const onContextComplete = async (ctx: ExtensionContext): Promise<string> => {
    if (!state.plan) {
      return "Context captured but no plan state available.";
    }

    let outcome: "PASS" | "FAIL" = "FAIL";

    try {
      const planDir = state.plan.directory;
      const planJsonPath = path.join(planDir, "plan.json");
      const subagentDir = await createSubagentDir(planDir, "architect");

      state.phase = "architect-running";
      widget?.update({
        phaseStatus: { index: 0, status: "completed" },
        activeIndex: 1,
        step: "spawning architect...",
        activity: "",
      });
      log("Spawning architect after context capture", { planDir, subagentDir });

      const extensionPath = path.resolve(import.meta.dirname, "../../extensions/koan.ts");

      const pollInterval = setInterval(async () => {
        const [s, logs] = await Promise.all([
          readProjection(subagentDir),
          readRecentLogs(subagentDir),
        ]);
        if (s) {
          widget?.update({
            step: s.stepName,
            activity: s.lastAction ?? "",
            logLines: logs,
          });
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
        widget?.update({
          phaseStatus: { index: 1, status: "failed" },
          step: "architect failed",
          activity: "",
        });
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
        widget?.update({
          phaseStatus: { index: 1, status: "failed" },
          step: "no plan produced",
          activity: "",
        });
        return "Context captured. Architect completed but produced no plan.";
      }

      state.phase = "plan-design-complete";
      log("Architect plan-design complete", { planDir });
      widget?.update({
        phaseStatus: { index: 1, status: "running" },
        step: "starting QR block...",
        activity: "",
        qrIterationsMax: MAX_FIX_ITERATIONS + 1,
        qrIteration: 1,
        qrMode: "initial",
        qrPhase: "execute",
      });

      const qr = await runPlanDesignWithQR(planDir, ctx.cwd, extensionPath, state, log, widget);
      if (qr.passed) outcome = "PASS";
      return `Context captured. Plan design complete.\n\n${qr.summary}`;
    } finally {
      if (widget) {
        widget.destroy();
        widget = null;
      }
      ctx.ui.notify(outcome, outcome === "PASS" ? "info" : "error");
    }
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
      setLogDir(planInfo.directory);

      log("Plan command invoked", {
        cwd: ctx.cwd,
        description,
        planId: planInfo.id,
        planDirectory: planInfo.directory,
      });

      // Destroy stale widget if re-entered
      if (widget) {
        widget.destroy();
        widget = null;
      }

      if (ctx.hasUI) {
        widget = new WidgetController(ctx.ui, planInfo.id);
      }

      await contextPhase.begin(description, planInfo, ctx);
    },

    async execute(ctx) {
      ctx.ui.notify("Execution mode is not yet implemented.", "warning");
    },

    async status(ctx) {
      ctx.ui.notify(`Phase: ${state.phase}`, "info");
    },
  };
}

// -- QR Block --

const QR_POOL_CONCURRENCY = 6;

async function runQRBlock(
  planDir: string,
  cwd: string,
  extensionPath: string,
  state: WorkflowState,
  log: Logger,
  widget: WidgetController | null,
): Promise<QRBlockResult> {
  // 1. Spawn decomposer subagent
  state.phase = "qr-decompose-running";
  widget?.update({ step: "qr-decompose: starting...", activity: "", qrPhase: "decompose" });
  const decomposeDir = await createSubagentDir(planDir, "qr-decomposer");

  const decomposePoll = setInterval(async () => {
    const [s, logs] = await Promise.all([
      readProjection(decomposeDir),
      readRecentLogs(decomposeDir),
    ]);
    if (s) {
      widget?.update({
        step: `qr-decompose: ${s.stepName}`,
        activity: s.lastAction ?? "",
        logLines: logs,
      });
    }
  }, 2000);

  const decompose = await spawnQRDecomposer({
    planDir,
    subagentDir: decomposeDir,
    cwd,
    extensionPath,
    log,
  });

  clearInterval(decomposePoll);

  if (decompose.exitCode !== 0) {
    state.phase = "qr-decompose-failed";
    const detail = decompose.stderr.slice(0, 500);
    log("QR decomposer failed", { exitCode: decompose.exitCode, stderr: detail });
    widget?.update({ step: "qr-decompose: failed", activity: "" });
    return { summary: `QR decompose failed (exit ${decompose.exitCode}).\n\nStderr:\n${detail}`, passed: false };
  }

  // 2. Read QR items
  const qrPath = path.join(planDir, "qr-plan-design.json");
  let qr: QRFile;
  try {
    const raw = await fs.readFile(qrPath, "utf8");
    qr = JSON.parse(raw) as QRFile;
  } catch (error) {
    state.phase = "qr-decompose-failed";
    const message = error instanceof Error ? error.message : String(error);
    log("Failed to read qr-plan-design.json after decompose", { error: message });
    return { summary: "QR decompose completed but produced no verifiable items.", passed: false };
  }

  if (qr.items.length === 0) {
    state.phase = "qr-decompose-failed";
    log("QR decompose produced no items");
    return { summary: "QR decompose completed but produced no items.", passed: false };
  }

  const itemIds = qr.items.map((i) => i.id);
  log("QR decompose complete", { itemCount: itemIds.length });
  widget?.update({ step: `qr-verify: 0/${itemIds.length}`, activity: "" });

  // 3. Spawn reviewer pool
  state.phase = "qr-verify-running";
  widget?.update({ qrPhase: "verify" });

  const result = await pool(
    itemIds,
    QR_POOL_CONCURRENCY,
    async (itemId) => {
      const reviewerDir = await createSubagentDir(planDir, `qr-reviewer-${itemId}`);
      return spawnReviewer({
        planDir,
        subagentDir: reviewerDir,
        cwd,
        extensionPath,
        itemId,
        log,
      });
    },
    (done, total) => widget?.update({ step: `qr-verify: ${done}/${total}` }),
  );

  // 4. Read final results
  state.phase = "qr-complete";
  let finalQR: QRFile;
  try {
    const raw = await fs.readFile(qrPath, "utf8");
    finalQR = JSON.parse(raw) as QRFile;
  } catch {
    finalQR = qr;
  }

  const pass = finalQR.items.filter((i) => i.status === "PASS").length;
  const fail = finalQR.items.filter((i) => i.status === "FAIL").length;
  const todo = finalQR.items.filter((i) => i.status === "TODO").length;
  const summary = `QR complete: ${pass} PASS, ${fail} FAIL, ${todo} TODO (${result.failed.length} reviewers failed).`;

  log("QR block complete", { pass, fail, todo, failedReviewers: result.failed });

  const passed = fail === 0 && result.failed.length === 0;
  widget?.update({ step: summary, activity: "" });
  return { summary, passed };
}

// -- Plan-design QR fix loop --

// Fix loop: architect -> QR -> [pass: done | fail: fix architect -> QR -> ...]
//
// Re-decomposes on each iteration rather than re-verifying only. The fix
// architect may change plan structure (add milestones, split intents, remove
// decisions); old QR items referencing stale scopes produce incorrect verdicts.
// Fresh decomposition generates items matched to the current plan state.
//
// The session's for-loop counter is the iteration source of truth. Each
// re-decompose writes a fresh qr-plan-design.json with iteration=1 and
// all-TODO items. The loop counter survives those resets.
async function runPlanDesignWithQR(
  planDir: string,
  cwd: string,
  extensionPath: string,
  state: WorkflowState,
  log: Logger,
  widget: WidgetController | null,
): Promise<QRBlockResult> {
  const qrPath = path.join(planDir, "qr-plan-design.json");

  // Initial QR (iteration 1)
  let qr = await runQRBlock(planDir, cwd, extensionPath, state, log, widget);
  if (qr.passed) {
    widget?.update({ qrPhase: "done", qrMode: null, qrIteration: null, qrIterationsMax: null, phaseStatus: { index: 1, status: "completed" } });
    return qr;
  }

  widget?.update({ qrPhase: "execute" });

  for (let iteration = 2; iteration <= MAX_FIX_ITERATIONS + 1; iteration++) {
    widget?.update({ qrIteration: iteration, qrMode: "fix", qrPhase: "execute" });

    // Read QR file for severity check
    let qrFile: QRFile;
    try {
      const raw = await fs.readFile(qrPath, "utf8");
      qrFile = JSON.parse(raw) as QRFile;
    } catch {
      log("Fix loop: failed to read QR file", { iteration });
      widget?.update({ qrPhase: "done", qrMode: null, qrIteration: null, qrIterationsMax: null });
      return { summary: "Fix loop aborted: cannot read QR file.", passed: false };
    }

    // Severity escalation: if no blocking failures remain at this
    // iteration, the plan passes without another fix attempt.
    // Example: iteration 3 drops COULD -- if only COULD items fail,
    // the plan is good enough and the loop terminates.
    if (qrPassesAtIteration(qrFile.items, iteration)) {
      const pass = qrFile.items.filter((i) => i.status === "PASS").length;
      const fail = qrFile.items.filter((i) => i.status === "FAIL").length;
      widget?.update({ qrPhase: "done", qrMode: null, qrIteration: null, qrIterationsMax: null, phaseStatus: { index: 1, status: "completed" } });
      return {
        passed: true,
        summary: `QR passed at iteration ${iteration} after severity de-escalation: ${pass} PASS, ${fail} FAIL (non-blocking).`,
      };
    }

    // Spawn fix-mode architect
    const fixIndex = iteration - 1;
    widget?.update({ step: `fix ${fixIndex}/${MAX_FIX_ITERATIONS}: spawning architect...`, activity: "", qrPhase: "execute" });

    const fixDir = await createSubagentDir(planDir, `architect-fix-${fixIndex}`);

    const fixPoll = setInterval(async () => {
      const [s, logs] = await Promise.all([
        readProjection(fixDir),
        readRecentLogs(fixDir),
      ]);
      if (s) {
        widget?.update({
          step: `fix ${fixIndex}/${MAX_FIX_ITERATIONS}: ${s.stepName}`,
          activity: s.lastAction ?? "",
          logLines: logs,
        });
      }
    }, 2000);

    const fixResult = await spawnArchitectFix({
      planDir,
      subagentDir: fixDir,
      cwd,
      extensionPath,
      fixPhase: "plan-design",
      log,
    });

    clearInterval(fixPoll);

    if (fixResult.exitCode !== 0) {
      log("Fix architect failed", { iteration: fixIndex, exitCode: fixResult.exitCode, stderr: fixResult.stderr.slice(0, 500) });
      widget?.update({ step: `fix ${fixIndex}/${MAX_FIX_ITERATIONS}: architect failed, re-running QR...`, activity: "" });
    }

    // Re-run full QR (decompose + verify)
    widget?.update({
      step: `fix ${fixIndex}/${MAX_FIX_ITERATIONS}: re-running QR...`,
      activity: "",
    });
    qr = await runQRBlock(planDir, cwd, extensionPath, state, log, widget);
    if (qr.passed) {
      widget?.update({ qrPhase: "done", qrMode: null, qrIteration: null, qrIterationsMax: null, phaseStatus: { index: 1, status: "completed" } });
      return qr;
    }

    widget?.update({ qrPhase: "execute" });
  }

  // Max iterations reached. MUST failures remaining after 5 fix attempts
  // indicate a structural problem -- silently passing would propagate a
  // known-broken plan downstream.
  widget?.update({ qrPhase: "done", qrMode: null, qrIteration: null, qrIterationsMax: null });
  return {
    passed: false,
    summary: `${qr.summary} (max ${MAX_FIX_ITERATIONS} fix iterations reached)`,
  };
}
