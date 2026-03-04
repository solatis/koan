// Parent session: orchestrates the koan planning workflow.
// Flow: export conversation -> plan-design(+QR) -> plan-code(+QR) -> plan-docs(+QR)
// -> mechanical plan.json->plan.md rendering for manual review.

import { promises as fs } from "node:fs";
import * as path from "node:path";

import type { AgentToolResult, ExtensionAPI, ExtensionCommandContext, ExtensionContext, ExtensionUIContext } from "@mariozechner/pi-coding-agent";

import { exportConversation } from "./conversation.js";
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
  type SpawnQRDecomposerOptions,
  type SpawnReviewerOptions,
  type SubagentResult,
} from "./subagent.js";
import { createLogger, setLogDir, type Logger } from "../utils/logger.js";
import { createSubagentDir } from "../utils/progress.js";
import { readProjection, readRecentLogs, type Projection, type LogLine } from "./lib/audit.js";
import type { WorkflowDispatch, PlanRef } from "./lib/dispatch.js";
import { pool } from "./lib/pool.js";
import type { QRFile } from "./qr/types.js";
import { MAX_FIX_ITERATIONS, qrPassesAtIteration } from "./qr/severity.js";
import { WidgetController, type WidgetUpdate } from "./ui/widget.js";
import { renderPlanMarkdownToFile } from "./plan/render.js";
import {
  mapSpawnContextToPhaseModelKey,
  resolvePhaseModelOverride,
  type SpawnContext,
} from "./model-resolver.js";
import type { PhaseRow } from "./model-phase.js";
import {
  readIpcFile,
  writeIpcFile,
  createAskResponse,
  createCancelledResponse,
  type IpcFile,
  type IpcResponse,
} from "./lib/ipc.js";
import { askSingleQuestionWithInlineNote } from "./ui/ask/ask-inline-ui.js";
import { askQuestionsWithTabs } from "./ui/ask/ask-tabs-ui.js";
import type { AskQuestion } from "./ui/ask/ask-logic.js";

type WorkPhaseKey = "plan-design" | "plan-code" | "plan-docs";

interface Session {
  plan(ctx: ExtensionContext): Promise<AgentToolResult<unknown>>;
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
  modelOverride?: string;
}

interface SpawnFixRunOptions extends SpawnWorkRunOptions {}

function qrFilePath(planDir: string, phase: WorkPhaseKey): string {
  return path.join(planDir, `qr-${phase}.json`);
}

function singleSubagentStart(role: string): WidgetUpdate {
  return {
    subagentRole: role,
    subagentModel: null,
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

interface ModelResolutionDeps {
  mapSpawnContextToPhaseModelKeyFn?: typeof mapSpawnContextToPhaseModelKey;
  resolvePhaseModelOverrideFn?: typeof resolvePhaseModelOverride;
}

interface QRSpawnResolutionDeps extends ModelResolutionDeps {
  spawnQRDecomposerFn?: typeof spawnQRDecomposer;
  spawnReviewerFn?: typeof spawnReviewer;
}

export async function resolveSpawnModelOverride(
  context: SpawnContext,
  phaseRow: PhaseRow,
  deps: ModelResolutionDeps = {},
): Promise<string | undefined> {
  const mapFn = deps.mapSpawnContextToPhaseModelKeyFn ?? mapSpawnContextToPhaseModelKey;
  const resolveFn = deps.resolvePhaseModelOverrideFn ?? resolvePhaseModelOverride;
  const key = mapFn(context, phaseRow);
  return await resolveFn(key);
}

export async function spawnWorkWithResolvedModel(
  phaseRow: PhaseRow,
  spawnWorkFn: (opts: SpawnWorkRunOptions) => Promise<SubagentResult>,
  opts: SpawnWorkRunOptions,
  deps: ModelResolutionDeps = {},
): Promise<SubagentResult> {
  const modelOverride = await resolveSpawnModelOverride("work-debut", phaseRow, deps);
  return await spawnWorkFn({ ...opts, modelOverride });
}

export async function spawnFixWithResolvedModel(
  phaseRow: PhaseRow,
  spawnFixFn: (opts: SpawnFixRunOptions) => Promise<SubagentResult>,
  opts: SpawnFixRunOptions,
  deps: ModelResolutionDeps = {},
): Promise<SubagentResult> {
  const modelOverride = await resolveSpawnModelOverride("fix", phaseRow, deps);
  return await spawnFixFn({ ...opts, modelOverride });
}

export async function spawnQRDecomposerWithResolvedModel(
  opts: SpawnQRDecomposerOptions,
  deps: QRSpawnResolutionDeps = {},
): Promise<SubagentResult> {
  const modelOverride = await resolveSpawnModelOverride("qr-decompose", opts.phase as PhaseRow, deps);
  const spawnFn = deps.spawnQRDecomposerFn ?? spawnQRDecomposer;
  return await spawnFn({ ...opts, modelOverride });
}

export async function spawnReviewerWithResolvedModel(
  opts: SpawnReviewerOptions,
  deps: QRSpawnResolutionDeps = {},
): Promise<SubagentResult> {
  const modelOverride = await resolveSpawnModelOverride("qr-verify", opts.phase as PhaseRow, deps);
  const spawnFn = deps.spawnReviewerFn ?? spawnReviewer;
  return await spawnFn({ ...opts, modelOverride });
}

// Routes an IpcFile ask request to the appropriate UI component and returns
// an IpcResponse. On any exception from the UI layer, the caller's catch
// block writes a cancelled response so the subagent unblocks.
async function handleAskRequest(
  ui: ExtensionUIContext,
  ipc: IpcFile,
): Promise<IpcResponse> {
  const { request } = ipc;
  const { questions } = request.payload;
  const questionsAsAsk = questions as AskQuestion[];

  if (questions.length === 1 && !questions[0].multi) {
    const selection = await askSingleQuestionWithInlineNote(ui, questionsAsAsk[0]);
    if (selection.selectedOptions.length === 0 && !selection.customInput) {
      return createCancelledResponse(request.id);
    }
    const answer: { id: string; selectedOptions: string[]; customInput?: string } = {
      id: questions[0].id,
      selectedOptions: selection.selectedOptions,
    };
    if (selection.customInput !== undefined) {
      answer.customInput = selection.customInput;
    }
    return createAskResponse(request.id, { answers: [answer] });
  }

  const tabResult = await askQuestionsWithTabs(ui, questionsAsAsk);
  if (tabResult.cancelled) {
    return createCancelledResponse(request.id);
  }

  const answers = questions.map((q, i) => {
    const sel = tabResult.selections[i] ?? { selectedOptions: [] };
    const answer: { id: string; selectedOptions: string[]; customInput?: string } = {
      id: q.id,
      selectedOptions: sel.selectedOptions,
    };
    if (sel.customInput !== undefined) {
      answer.customInput = sel.customInput;
    }
    return answer;
  });

  return createAskResponse(request.id, { answers });
}

// Encapsulates the poll-with-request-detection pattern used by both
// the work poll loop and the fix poll loop. Returns a setInterval ID.
function pollWithIpcDetection(
  subagentDir: string,
  widget: WidgetController | null,
  ui: ExtensionUIContext | null,
  stepPrefix: string,
  updateFromProjection: (p: Projection, logs: LogLine[]) => void,
): ReturnType<typeof setInterval> {
  let pendingRequestId: string | null = null;

  return setInterval(async () => {
    const [projection, logs] = await Promise.all([
      readProjection(subagentDir),
      readRecentLogs(subagentDir),
    ]);
    if (projection) {
      updateFromProjection(projection, logs);
    }

    // IPC request detection — skip if already handling a request or no UI
    if (pendingRequestId || !ui) return;

    const ipc = await readIpcFile(subagentDir);
    if (!ipc || !ipc.request || ipc.response !== null) return;

    pendingRequestId = ipc.request.id;
    try {
      widget?.update({
        step: `${stepPrefix}: waiting for user input...`,
        activity: ipc.request.payload.questions[0]?.question ?? "",
      });

      const response = await handleAskRequest(ui, ipc);
      const updated: IpcFile = { request: ipc.request, response };
      await writeIpcFile(subagentDir, updated);
    } catch {
      // On error, write cancelled response so subagent unblocks.
      // The inner try-catch guards against I/O failures during error
      // recovery — an unguarded throw here would propagate as an
      // unhandled async rejection in the setInterval callback,
      // crashing the parent process (Node.js ≥15 default behavior).
      try {
        const cancelled = createCancelledResponse(ipc.request.id);
        await writeIpcFile(subagentDir, { request: ipc.request, response: cancelled });
      } catch {
        // I/O failed during error recovery; subagent remains blocked
        // until parent terminates. No further action possible.
      }
    } finally {
      pendingRequestId = null;
    }
  }, 2000);
}

export function createSession(pi: ExtensionAPI, dispatch: WorkflowDispatch, planRef: PlanRef): Session {
  const state: WorkflowState = createInitialState();
  const log = createLogger("Session");
  let widget: WidgetController | null = null;

  return {
    async plan(ctx: ExtensionContext): Promise<AgentToolResult<unknown>> {
      const planInfo = await createPlanInfo("", ctx.cwd);
      initializePlanState(state, planInfo, "");

      // Wire plan directory for subagent dispatch and logging.
      planRef.dir = planInfo.directory;
      setLogDir(planInfo.directory);

      log("Plan tool invoked", {
        cwd: ctx.cwd,
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

      // Export conversation to plan directory.
      // Agents that need session context can Read this file.
      await exportConversation(ctx.sessionManager, planInfo.directory);
      log("Conversation exported", { planDir: planInfo.directory });

      let outcome: "PASS" | "FAIL" = "FAIL";
      try {
        const planDir = planInfo.directory;
        const extensionPath = path.resolve(import.meta.dirname, "../../extensions/koan.ts");
        const ui = ctx.hasUI ? ctx.ui : null;

        // widgetIndex 0=design, 1=code, 2=docs
        const phases: PhaseRunConfig[] = [
          {
            key: "plan-design",
            label: "Plan design",
            widgetIndex: 0,
            role: "architect",
            spawnWork: (opts) => spawnArchitect(opts),
            spawnFix: (opts) => spawnArchitectFix({ ...opts, fixPhase: "plan-design" }),
          },
          {
            key: "plan-code",
            label: "Plan code",
            widgetIndex: 1,
            role: "developer",
            spawnWork: (opts) => spawnDeveloper(opts),
            spawnFix: (opts) => spawnDeveloperFix({ ...opts, fixPhase: "plan-code" }),
          },
          {
            key: "plan-docs",
            label: "Plan docs",
            widgetIndex: 2,
            role: "technical-writer",
            spawnWork: (opts) => spawnTechnicalWriter(opts),
            spawnFix: (opts) => spawnTechnicalWriterFix({ ...opts, fixPhase: "plan-docs" }),
          },
        ];

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
            ui,
          );

          phaseSummaries.push(`${phase.label}: ${result.summary}`);
          if (!result.passed) {
            return {
              content: [{ type: "text" as const, text: `Planning failed at ${phase.label}.\n\n${phaseSummaries.join("\n")}` }],
              details: undefined,
            };
          }
        }

        try {
          await renderPlanMarkdownToFile(planDir);
        } catch (error) {
          const message = error instanceof Error ? error.message : String(error);
          log("Failed to render plan.md", { error: message, planDir });
          return {
            content: [{ type: "text" as const, text: `Planning phases completed, but plan markdown rendering failed: ${message}\n\n${phaseSummaries.join("\n")}` }],
            details: undefined,
          };
        }

        state.phase = "plan-docs-complete";
        widget?.update({
          activeIndex: -1,
          step: "planning complete; awaiting manual review of plan.md",
          activity: "",
        });

        outcome = "PASS";
        return {
          content: [{ type: "text" as const, text: `Planning complete.\n\n${phaseSummaries.join("\n")}` }],
          details: undefined,
        };
      } finally {
        if (widget) {
          widget.destroy();
          widget = null;
        }
        ctx.ui.notify(outcome, outcome === "PASS" ? "info" : "error");
      }
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
  ui: ExtensionUIContext | null,
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

  const pollInterval = pollWithIpcDetection(
    subagentDir,
    widget,
    ui,
    phase.key,
    (projection, logs) => {
      widget?.update({
        step: `${phase.key}: ${projection.stepName}`,
        activity: projection.lastAction ?? "",
        logLines: logs,
        ...singleSubagentFromProjection(projection),
      });
    },
  );

  const workResult = await spawnWorkWithResolvedModel(
    phase.key as PhaseRow,
    phase.spawnWork,
    {
      planDir,
      subagentDir,
      cwd,
      extensionPath,
      log,
    },
  );

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
    ui,
  );

  if (qr.passed) {
    state.phase = phaseCompleteState(phase.key);
    widget?.update({ phaseStatus: { index: phase.widgetIndex, status: "completed" } });
  } else {
    widget?.update({ phaseStatus: { index: phase.widgetIndex, status: "failed" } });
  }

  return qr;
}


async function runQRDecompose(
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

  const decompose = await spawnQRDecomposerWithResolvedModel({
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

  return { summary: `${phase} QR decompose complete.`, passed: true };
}

async function runQRVerify(
  planDir: string,
  cwd: string,
  extensionPath: string,
  phase: WorkPhaseKey,
  state: WorkflowState,
  log: Logger,
  widget: WidgetController | null,
): Promise<QRBlockResult> {
  const qrPath = qrFilePath(planDir, phase);

  let qr: QRFile;
  try {
    const raw = await fs.readFile(qrPath, "utf8");
    qr = JSON.parse(raw) as QRFile;
  } catch (error) {
    state.phase = "qr-decompose-failed";
    const message = error instanceof Error ? error.message : String(error);
    log("Failed to read QR file for verify", { phase, error: message });
    return { summary: `${phase} QR verify aborted: cannot read QR file.`, passed: false };
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

  // Group TODO items by group_id for batch verification.
  // Items sharing a group_id are verified by a single subagent, amortizing
  // process startup cost. Items without group_id are treated as singletons.
  const todoItems = qr.items.filter((i) => i.status === "TODO");
  const groups = new Map<string, string[]>();
  for (const item of todoItems) {
    const gid = item.group_id ?? item.id;
    const existing = groups.get(gid);
    if (existing) {
      existing.push(item.id);
    } else {
      groups.set(gid, [item.id]);
    }
  }
  const groupEntries = Array.from(groups.entries()); // [groupId, itemIds[]]
  const totalItems = qr.items.length;
  const totalTodoItems = todoItems.length;
  const preservedPass = qr.items.filter((i) => i.status === "PASS").length;
  const initialFail = qr.items.filter((i) => i.status === "FAIL").length;

  widget?.update({
    step: `${phase} qr-verify: 0/${groupEntries.length} groups (${totalTodoItems} items)`,
    activity: "",
    qrPhase: "verify",
    qrTotal: totalItems,
    qrDone: preservedPass,
    qrPass: preservedPass,
    qrFail: initialFail,
    qrTodo: totalTodoItems,
    subagentRole: "reviewer",
    subagentModel: null,
    subagentParallelCount: QR_POOL_CONCURRENCY,
    subagentQueued: groupEntries.length,
    subagentActive: 0,
    subagentDone: 0,
  });

  log("QR verify: grouped items for dispatch", {
    phase,
    totalItems: totalTodoItems,
    groups: groupEntries.length,
    groupSizes: groupEntries.map(([gid, ids]) => `${gid}:${ids.length}`),
  });

  state.phase = "qr-verify-running";

  let verifyDone = 0;
  let failedReviewers: string[] = [];

  if (groupEntries.length > 0) {
    const groupIds = groupEntries.map(([gid]) => gid);

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

    // Build a map from groupId -> itemIds for the pool worker.
    const groupItemMap = new Map(groupEntries);

    try {
      let reviewerModel: string | null = null;
      const result = await pool(
        groupIds,
        QR_POOL_CONCURRENCY,
        async (groupId) => {
          const itemIds = groupItemMap.get(groupId)!;
          const dirSuffix = itemIds.length === 1
            ? `qr-reviewer-${phase}-${itemIds[0]}`
            : `qr-reviewer-${phase}-group-${groupId}`;
          const reviewerDir = await createSubagentDir(planDir, dirSuffix);
          const r = await spawnReviewerWithResolvedModel({
            planDir,
            subagentDir: reviewerDir,
            cwd,
            extensionPath,
            phase,
            itemIds,
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
            step: `${phase} qr-verify: ${progress.done}/${progress.total} groups`,
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
  const summary = `${phase} QR complete: ${pass} PASS, ${fail} FAIL, ${todo} TODO (${failedReviewers.length} reviewer groups failed).`;

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
    subagentDone: groupEntries.length,
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
  ui: ExtensionUIContext | null,
): Promise<QRBlockResult> {
  const qrPath = qrFilePath(planDir, phase.key);

  const decompose = await runQRDecompose(planDir, cwd, extensionPath, phase.key, state, log, widget);
  if (!decompose.passed) {
    widget?.update({ phaseStatus: { index: phase.widgetIndex, status: "failed" } });
    return decompose;
  }

  let qr = await runQRVerify(planDir, cwd, extensionPath, phase.key, state, log, widget);
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

    const fixPoll = pollWithIpcDetection(
      fixDir,
      widget,
      ui,
      `${phase.key} fix ${fixIndex}/${MAX_FIX_ITERATIONS}`,
      (projection, logs) => {
        widget?.update({
          step: `${phase.key} fix ${fixIndex}/${MAX_FIX_ITERATIONS}: ${projection.stepName}`,
          activity: projection.lastAction ?? "",
          logLines: logs,
          ...singleSubagentFromProjection(projection),
        });
      },
    );

    const fixResult = await spawnFixWithResolvedModel(
      phase.key as PhaseRow,
      phase.spawnFix,
      {
        planDir,
        subagentDir: fixDir,
        cwd,
        extensionPath,
        log,
      },
    );

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

    qr = await runQRVerify(planDir, cwd, extensionPath, phase.key, state, log, widget);
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
