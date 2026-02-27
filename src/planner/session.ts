// Parent session: orchestrates the koan planning workflow.
// Flow: context capture -> plan-design(+QR) -> plan-code(+QR) -> plan-docs(+QR)
// -> mechanical plan.json->plan.md rendering for manual review.

import { promises as fs } from "node:fs";
import * as path from "node:path";

import type { ExtensionAPI, ExtensionCommandContext, ExtensionContext } from "@mariozechner/pi-coding-agent";

import { ContextCapturePhase } from "./phases/context-capture/phase.js";
import { createInitialState, initializePlanState, type WorkflowState } from "./state.js";
import { createPlanInfo } from "../utils/plan.js";
import {
  spawnArchitect,
  spawnArchitectFix,
  spawnDeveloper,
  spawnDeveloperFix,
  spawnTechnicalWriter,
  spawnTechnicalWriterFix,
  spawnQRDecomposer,
  spawnReviewer,
  type SubagentResult,
} from "./subagent.js";
import { createLogger, setLogDir, type Logger } from "../utils/logger.js";
import { createSubagentDir } from "../utils/progress.js";
import { readProjection, readRecentLogs, type Projection } from "./lib/audit.js";
import type { WorkflowDispatch, PlanRef } from "./lib/dispatch.js";
import { pool } from "./lib/pool.js";
import type { QRFile } from "./qr/types.js";
import { MAX_FIX_ITERATIONS, qrPassesAtIteration } from "./qr/severity.js";
import { WidgetController, type WidgetUpdate } from "./ui/widget.js";
import { renderPlanMarkdownToFile } from "./plan/render.js";

type WorkPhaseKey = "plan-design" | "plan-code" | "plan-docs";

interface Session {
  plan(args: string, ctx: ExtensionCommandContext): Promise<void>;
  execute(_ctx: ExtensionCommandContext): Promise<void>;
  status(ctx: ExtensionCommandContext): Promise<void>;
}

interface QRBlockResult {
  summary: string;
  passed: boolean;
}

interface PhaseRunConfig {
  key: WorkPhaseKey;
  label: string;
  widgetIndex: number;
  role: "architect" | "developer" | "technical-writer";
  spawnWork: (opts: SpawnWorkRunOptions) => Promise<SubagentResult>;
  spawnFix: (opts: SpawnFixRunOptions) => Promise<SubagentResult>;
}

interface SpawnWorkRunOptions {
  planDir: string;
  subagentDir: string;
  cwd: string;
  extensionPath: string;
  log: Logger;
}

interface SpawnFixRunOptions extends SpawnWorkRunOptions {}

function qrFilePath(planDir: string, phase: WorkPhaseKey): string {
  return path.join(planDir, `qr-${phase}.json`);
}

function singleSubagentStart(role: string): WidgetUpdate {
  return {
    subagentRole: role,
    subagentParallelCount: 1,
    subagentQueued: 0,
    subagentActive: 1,
    subagentDone: 0,
  };
}

function singleSubagentFromProjection(p: Projection): WidgetUpdate {
  const running = p.status === "running";
  return {
    subagentRole: p.role,
    subagentModel: p.model,
    subagentParallelCount: 1,
    subagentQueued: 0,
    subagentActive: running ? 1 : 0,
    subagentDone: running ? 0 : 1,
  };
}

function phaseRunningState(phase: WorkPhaseKey): WorkflowState["phase"] {
  if (phase === "plan-design") return "architect-running";
  if (phase === "plan-code") return "plan-code-running";
  return "plan-docs-running";
}

function phaseCompleteState(phase: WorkPhaseKey): WorkflowState["phase"] {
  if (phase === "plan-design") return "plan-design-complete";
  if (phase === "plan-code") return "plan-code-complete";
  return "plan-docs-complete";
}

export function createSession(pi: ExtensionAPI, dispatch: WorkflowDispatch, planRef: PlanRef): Session {
  const state: WorkflowState = createInitialState();
  const log = createLogger("Session");
  let widget: WidgetController | null = null;

  const onContextComplete = async (ctx: ExtensionContext): Promise<string> => {
    if (!state.plan) {
      return "Context captured but no plan state available.";
    }

    let outcome: "PASS" | "FAIL" = "FAIL";

    try {
      const planDir = state.plan.directory;
      const extensionPath = path.resolve(import.meta.dirname, "../../extensions/koan.ts");

      const phases: PhaseRunConfig[] = [
        {
          key: "plan-design",
          label: "Plan design",
          widgetIndex: 1,
          role: "architect",
          spawnWork: (opts) => spawnArchitect(opts),
          spawnFix: (opts) => spawnArchitectFix({ ...opts, fixPhase: "plan-design" }),
        },
        {
          key: "plan-code",
          label: "Plan code",
          widgetIndex: 2,
          role: "developer",
          spawnWork: (opts) => spawnDeveloper(opts),
          spawnFix: (opts) => spawnDeveloperFix({ ...opts, fixPhase: "plan-code" }),
        },
        {
          key: "plan-docs",
          label: "Plan docs",
          widgetIndex: 3,
          role: "technical-writer",
          spawnWork: (opts) => spawnTechnicalWriter(opts),
          spawnFix: (opts) => spawnTechnicalWriterFix({ ...opts, fixPhase: "plan-docs" }),
        },
      ];

      widget?.update({
        phaseStatus: { index: 0, status: "completed" },
        activeIndex: 1,
        step: "context captured; starting planning phases...",
        activity: "",
      });

      const phaseSummaries: string[] = [];
      for (const phase of phases) {
        const result = await runPlanningPhase(
          phase,
          planDir,
          ctx.cwd,
          extensionPath,
          state,
          log,
          widget,
        );

        phaseSummaries.push(`${phase.label}: ${result.summary}`);
        if (!result.passed) {
          return `Context captured. ${phase.label} failed.\n\n${phaseSummaries.join("\n")}`;
        }
      }

      let planMdPath: string;
      try {
        planMdPath = await renderPlanMarkdownToFile(planDir);
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        log("Failed to render plan.md", { error: message, planDir });
        return `Planning phases completed, but plan markdown rendering failed: ${message}`;
      }

      state.phase = "plan-docs-complete";
      widget?.update({
        activeIndex: -1,
        step: "planning complete; awaiting manual review of plan.md",
        activity: "",
      });

      outcome = "PASS";
      return [
        "Context captured. Planning complete.",
        "",
        ...phaseSummaries,
        "",
        `Plan markdown: ${planMdPath}`,
        "PAUSE: Please review this file manually before /koan execute.",
      ].join("\n");
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

const QR_POOL_CONCURRENCY = 6;

async function runPlanningPhase(
  phase: PhaseRunConfig,
  planDir: string,
  cwd: string,
  extensionPath: string,
  state: WorkflowState,
  log: Logger,
  widget: WidgetController | null,
): Promise<QRBlockResult> {
  state.phase = phaseRunningState(phase.key);

  widget?.update({
    phaseStatus: { index: phase.widgetIndex, status: "running" },
    activeIndex: phase.widgetIndex,
    step: `${phase.key}: spawning ${phase.role}...`,
    activity: "",
    qrIterationsMax: MAX_FIX_ITERATIONS + 1,
    qrIteration: 1,
    qrMode: "initial",
    qrPhase: "execute",
    qrDone: null,
    qrTotal: null,
    qrPass: null,
    qrFail: null,
    qrTodo: null,
    ...singleSubagentStart(phase.role),
  });

  const subagentDir = await createSubagentDir(planDir, `${phase.role}-${phase.key}`);

  const pollInterval = setInterval(async () => {
    const [projection, logs] = await Promise.all([readProjection(subagentDir), readRecentLogs(subagentDir)]);
    if (!projection) return;
    widget?.update({
      step: `${phase.key}: ${projection.stepName}`,
      activity: projection.lastAction ?? "",
      logLines: logs,
      ...singleSubagentFromProjection(projection),
    });
  }, 2000);

  const workResult = await phase.spawnWork({
    planDir,
    subagentDir,
    cwd,
    extensionPath,
    log,
  });

  clearInterval(pollInterval);

  if (workResult.exitCode !== 0) {
    const detail = workResult.stderr.slice(0, 500);
    log(`${phase.key} subagent failed`, { exitCode: workResult.exitCode, stderr: detail });
    widget?.update({
      phaseStatus: { index: phase.widgetIndex, status: "failed" },
      step: `${phase.key}: worker failed`,
      activity: "",
      subagentActive: 0,
      subagentDone: 1,
    });
    return { summary: `${phase.label} subagent failed (exit ${workResult.exitCode}).\n\nStderr:\n${detail}`, passed: false };
  }

  const planJsonPath = path.join(planDir, "plan.json");
  try {
    await fs.access(planJsonPath);
  } catch {
    log(`${phase.key} completed but plan.json missing`, { planJsonPath });
    widget?.update({
      phaseStatus: { index: phase.widgetIndex, status: "failed" },
      step: `${phase.key}: no plan produced`,
      activity: "",
      subagentActive: 0,
      subagentDone: 1,
    });
    return { summary: `${phase.label} completed but produced no plan.json.`, passed: false };
  }

  state.phase = phaseCompleteState(phase.key);
  widget?.update({
    step: `${phase.key}: starting QR block...`,
    activity: "",
    qrIteration: 1,
    qrMode: "initial",
    qrPhase: "execute",
    qrDone: null,
    qrTotal: null,
    qrPass: null,
    qrFail: null,
    qrTodo: null,
    subagentActive: 0,
    subagentDone: 1,
  });

  const qr = await runPhaseWithQR(
    phase,
    planDir,
    cwd,
    extensionPath,
    state,
    log,
    widget,
  );

  if (qr.passed) {
    state.phase = phaseCompleteState(phase.key);
    widget?.update({ phaseStatus: { index: phase.widgetIndex, status: "completed" } });
  } else {
    widget?.update({ phaseStatus: { index: phase.widgetIndex, status: "failed" } });
  }

  return qr;
}

async function runQRBlock(
  planDir: string,
  cwd: string,
  extensionPath: string,
  phase: WorkPhaseKey,
  state: WorkflowState,
  log: Logger,
  widget: WidgetController | null,
): Promise<QRBlockResult> {
  const qrPath = qrFilePath(planDir, phase);
  const keyOf = (scope: string, check: string): string => `${scope}\u0000${check}`;

  const previousPassKeys = new Set<string>();
  try {
    const raw = await fs.readFile(qrPath, "utf8");
    const prev = JSON.parse(raw) as QRFile;
    for (const item of prev.items) {
      if (item.status === "PASS") previousPassKeys.add(keyOf(item.scope, item.check));
    }
  } catch {
    // First QR run for this phase.
  }

  state.phase = "qr-decompose-running";
  widget?.update({
    step: `${phase} qr-decompose: starting...`,
    activity: "",
    qrPhase: "decompose",
    qrDone: null,
    qrTotal: null,
    qrPass: null,
    qrFail: null,
    qrTodo: null,
    ...singleSubagentStart("qr-decomposer"),
  });

  const decomposeDir = await createSubagentDir(planDir, `qr-decomposer-${phase}`);

  const decomposePoll = setInterval(async () => {
    const [projection, logs] = await Promise.all([readProjection(decomposeDir), readRecentLogs(decomposeDir)]);
    if (!projection) return;
    widget?.update({
      step: `${phase} qr-decompose: ${projection.stepName}`,
      activity: projection.lastAction ?? "",
      logLines: logs,
      ...singleSubagentFromProjection(projection),
    });
  }, 2000);

  const decompose = await spawnQRDecomposer({
    planDir,
    subagentDir: decomposeDir,
    cwd,
    extensionPath,
    phase,
    log,
  });

  clearInterval(decomposePoll);

  if (decompose.exitCode !== 0) {
    state.phase = "qr-decompose-failed";
    const detail = decompose.stderr.slice(0, 500);
    log("QR decomposer failed", { phase, exitCode: decompose.exitCode, stderr: detail });
    widget?.update({ step: `${phase} qr-decompose: failed`, activity: "", subagentActive: 0, subagentDone: 1 });
    return { summary: `${phase} QR decompose failed (exit ${decompose.exitCode}).\n\nStderr:\n${detail}`, passed: false };
  }

  let qr: QRFile;
  try {
    const raw = await fs.readFile(qrPath, "utf8");
    qr = JSON.parse(raw) as QRFile;
  } catch (error) {
    state.phase = "qr-decompose-failed";
    const message = error instanceof Error ? error.message : String(error);
    log("Failed to read QR file after decompose", { phase, error: message });
    return { summary: `${phase} QR decompose completed but produced no verifiable items.`, passed: false };
  }

  if (qr.items.length === 0) {
    state.phase = "qr-decompose-failed";
    log("QR decompose produced no items", { phase });
    return { summary: `${phase} QR decompose completed but produced no items.`, passed: false };
  }

  const carriedPasses = qr.items.filter((item) => item.status !== "PASS" && previousPassKeys.has(keyOf(item.scope, item.check))).length;
  if (carriedPasses > 0) {
    qr = {
      ...qr,
      items: qr.items.map((item) =>
        previousPassKeys.has(keyOf(item.scope, item.check))
          ? { ...item, status: "PASS", finding: null }
          : item),
    };
    try {
      const tmpPath = `${qrPath}.tmp`;
      await fs.writeFile(tmpPath, `${JSON.stringify(qr, null, 2)}\n`, "utf8");
      await fs.rename(tmpPath, qrPath);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      log("Failed to persist carried PASS statuses", { phase, error: message });
      return { summary: `${phase} QR verify aborted: failed to preserve PASS statuses.`, passed: false };
    }
  }

  const resetFailures = qr.items.filter((i) => i.status === "FAIL").length;
  if (resetFailures > 0) {
    qr = {
      ...qr,
      items: qr.items.map((item) => (item.status === "FAIL" ? { ...item, status: "TODO", finding: null } : item)),
    };
    try {
      const tmpPath = `${qrPath}.tmp`;
      await fs.writeFile(tmpPath, `${JSON.stringify(qr, null, 2)}\n`, "utf8");
      await fs.rename(tmpPath, qrPath);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      log("Failed to persist QR FAIL->TODO reset", { phase, error: message });
      return { summary: `${phase} QR verify aborted: failed to prepare QR item states.`, passed: false };
    }
  }

  const verifyIds = qr.items.filter((i) => i.status === "TODO").map((i) => i.id);
  const totalItems = qr.items.length;
  const preservedPass = qr.items.filter((i) => i.status === "PASS").length;
  const initialFail = qr.items.filter((i) => i.status === "FAIL").length;
  const initialTodo = qr.items.filter((i) => i.status === "TODO").length;

  widget?.update({
    step: `${phase} qr-verify: 0/${verifyIds.length}`,
    activity: "",
    qrTotal: totalItems,
    qrDone: preservedPass,
    qrPass: preservedPass,
    qrFail: initialFail,
    qrTodo: initialTodo,
    subagentRole: "reviewer",
    subagentParallelCount: QR_POOL_CONCURRENCY,
    subagentQueued: verifyIds.length,
    subagentActive: 0,
    subagentDone: 0,
  });

  state.phase = "qr-verify-running";
  widget?.update({ qrPhase: "verify" });

  let verifyDone = 0;
  let failedReviewers: string[] = [];

  if (verifyIds.length > 0) {
    const verifyStatsPoll = setInterval(async () => {
      try {
        const raw = await fs.readFile(qrPath, "utf8");
        const current = JSON.parse(raw) as QRFile;
        const pass = current.items.filter((i) => i.status === "PASS").length;
        const fail = current.items.filter((i) => i.status === "FAIL").length;
        const todo = current.items.filter((i) => i.status === "TODO").length;
        widget?.update({
          qrPass: pass,
          qrFail: fail,
          qrTodo: todo,
          qrDone: preservedPass + verifyDone,
          qrTotal: current.items.length,
        });
      } catch {
        // Ignore transient read races while reviewers write.
      }
    }, 2000);

    try {
      let reviewerModel: string | null = null;
      const result = await pool(
        verifyIds,
        QR_POOL_CONCURRENCY,
        async (itemId) => {
          const reviewerDir = await createSubagentDir(planDir, `qr-reviewer-${phase}-${itemId}`);
          const r = await spawnReviewer({
            planDir,
            subagentDir: reviewerDir,
            cwd,
            extensionPath,
            phase,
            itemId,
            log,
          });

          if (reviewerModel === null) {
            const projection = await readProjection(reviewerDir);
            reviewerModel = projection?.model ?? null;
            if (reviewerModel) widget?.update({ subagentModel: reviewerModel });
          }

          return r;
        },
        (progress) => {
          verifyDone = progress.done;
          widget?.update({
            step: `${phase} qr-verify: ${progress.done}/${progress.total}`,
            qrDone: preservedPass + progress.done,
            qrTotal: totalItems,
            subagentQueued: progress.queued,
            subagentActive: progress.active,
            subagentDone: progress.done,
          });
        },
      );
      failedReviewers = result.failed;
    } finally {
      clearInterval(verifyStatsPoll);
    }
  }

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
  const summary = `${phase} QR complete: ${pass} PASS, ${fail} FAIL, ${todo} TODO (${failedReviewers.length} reviewers failed).`;

  const passed = fail === 0 && failedReviewers.length === 0;
  widget?.update({
    step: summary,
    activity: "",
    qrDone: pass + fail,
    qrTotal: totalItems,
    qrPass: pass,
    qrFail: fail,
    qrTodo: todo,
    subagentQueued: 0,
    subagentActive: 0,
    subagentDone: verifyIds.length,
  });
  return { summary, passed };
}

async function runPhaseWithQR(
  phase: PhaseRunConfig,
  planDir: string,
  cwd: string,
  extensionPath: string,
  state: WorkflowState,
  log: Logger,
  widget: WidgetController | null,
): Promise<QRBlockResult> {
  const qrPath = qrFilePath(planDir, phase.key);

  let qr = await runQRBlock(planDir, cwd, extensionPath, phase.key, state, log, widget);
  if (qr.passed) {
    widget?.update({ qrPhase: "done", phaseStatus: { index: phase.widgetIndex, status: "completed" } });
    return qr;
  }

  widget?.update({ qrPhase: "execute", qrDone: null, qrTotal: null, qrPass: null, qrFail: null, qrTodo: null });

  for (let iteration = 2; iteration <= MAX_FIX_ITERATIONS + 1; iteration++) {
    widget?.update({
      qrIteration: iteration,
      qrMode: "fix",
      qrPhase: "execute",
      qrDone: null,
      qrTotal: null,
      qrPass: null,
      qrFail: null,
      qrTodo: null,
    });

    let qrFile: QRFile;
    try {
      const raw = await fs.readFile(qrPath, "utf8");
      qrFile = JSON.parse(raw) as QRFile;
    } catch {
      log("Fix loop: failed to read QR file", { phase: phase.key, iteration });
      widget?.update({ qrPhase: "done" });
      return { summary: `${phase.key} fix loop aborted: cannot read QR file.`, passed: false };
    }

    if (qrPassesAtIteration(qrFile.items, iteration)) {
      const pass = qrFile.items.filter((i) => i.status === "PASS").length;
      const fail = qrFile.items.filter((i) => i.status === "FAIL").length;
      const todo = qrFile.items.filter((i) => i.status === "TODO").length;
      widget?.update({
        qrPhase: "done",
        qrDone: pass + fail,
        qrTotal: qrFile.items.length,
        qrPass: pass,
        qrFail: fail,
        qrTodo: todo,
        phaseStatus: { index: phase.widgetIndex, status: "completed" },
      });
      return {
        passed: true,
        summary: `${phase.key} QR passed at iteration ${iteration} after severity de-escalation: ${pass} PASS, ${fail} FAIL (non-blocking).`,
      };
    }

    const fixIndex = iteration - 1;
    widget?.update({
      step: `${phase.key} fix ${fixIndex}/${MAX_FIX_ITERATIONS}: spawning ${phase.role}...`,
      activity: "",
      qrPhase: "execute",
      ...singleSubagentStart(phase.role),
    });

    const fixDir = await createSubagentDir(planDir, `${phase.role}-fix-${phase.key}-${fixIndex}`);

    const fixPoll = setInterval(async () => {
      const [projection, logs] = await Promise.all([readProjection(fixDir), readRecentLogs(fixDir)]);
      if (!projection) return;
      widget?.update({
        step: `${phase.key} fix ${fixIndex}/${MAX_FIX_ITERATIONS}: ${projection.stepName}`,
        activity: projection.lastAction ?? "",
        logLines: logs,
        ...singleSubagentFromProjection(projection),
      });
    }, 2000);

    const fixResult = await phase.spawnFix({
      planDir,
      subagentDir: fixDir,
      cwd,
      extensionPath,
      log,
    });

    clearInterval(fixPoll);

    if (fixResult.exitCode !== 0) {
      log("Fix worker failed", {
        phase: phase.key,
        iteration: fixIndex,
        exitCode: fixResult.exitCode,
        stderr: fixResult.stderr.slice(0, 500),
      });
      widget?.update({
        step: `${phase.key} fix ${fixIndex}/${MAX_FIX_ITERATIONS}: worker failed, re-running QR...`,
        activity: "",
        subagentActive: 0,
        subagentDone: 1,
      });
    }

    widget?.update({
      step: `${phase.key} fix ${fixIndex}/${MAX_FIX_ITERATIONS}: re-running QR...`,
      activity: "",
      subagentActive: 0,
      subagentDone: 1,
    });

    qr = await runQRBlock(planDir, cwd, extensionPath, phase.key, state, log, widget);
    if (qr.passed) {
      widget?.update({ qrPhase: "done", phaseStatus: { index: phase.widgetIndex, status: "completed" } });
      return qr;
    }

    widget?.update({ qrPhase: "execute", qrDone: null, qrTotal: null, qrPass: null, qrFail: null, qrTodo: null });
  }

  widget?.update({ qrPhase: "done" });
  return {
    passed: false,
    summary: `${phase.key} ${qr.summary} (max ${MAX_FIX_ITERATIONS} fix iterations reached)`,
  };
}
