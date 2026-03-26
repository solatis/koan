// Epic pipeline driver — deterministic coordinator for the full epic lifecycle.
// Reads JSON state and exit codes; applies routing rules. Never parses markdown.
// Per AGENTS.md: driver owns .json state; LLMs own .md files.
//
// Spawn pattern used throughout: spawnSubagent(task, subagentDir, opts).
// epicDir is part of the task (written to task.json) rather than SpawnOptions
// because it is subagent configuration, not process infrastructure. SpawnOptions
// holds only what the OS-level spawn needs: cwd, extensionPath, model, webServer,
// and the debug mode flag.

import { promises as fs } from "node:fs";
import * as path from "node:path";

import {
  loadEpicState,
  saveEpicState,
  loadStoryState,
  saveStoryState,
  loadAllStoryStates,
  ensureSubagentDirectory,
  ensureStoryDirectory,
  discoverStoryIds,
  readWorkflowDecision,
} from "./epic/state.js";
import { listArtifacts } from "./epic/artifacts.js";
import { spawnSubagent, type SpawnOptions, type SubagentResult } from "./subagent.js";
import type { SubagentTask, WorkflowOrchestratorTask } from "./lib/task.js";
import type { Logger } from "../utils/logger.js";
import type { StoryState } from "./epic/types.js";
import type { WebServerHandle } from "./web/server-types.js";
import type { SubagentRole, EpicPhase } from "./types.js";
import {
  getSuccessorPhases,
  isAutoAdvance,
  isStubPhase,
  isValidTransition,
  PHASE_DESCRIPTIONS,
} from "./lib/phase-dag.js";

// ---------------------------------------------------------------------------
// readStoryTitle
// ---------------------------------------------------------------------------

async function readStoryTitle(epicDir: string, storyId: string): Promise<string> {
  try {
    const raw = await fs.readFile(path.join(epicDir, "stories", storyId, "story.md"), "utf8");
    for (const rawLine of raw.split("\n")) {
      const l = rawLine.trim();
      if (!l) continue;
      const text = l.replace(/^#+\s*/, "").trim();
      if (text) return text.slice(0, 80);
    }
    return storyId;
  } catch {
    return storyId;
  }
}

// ---------------------------------------------------------------------------
// Routing (dormant — used when execution phase is implemented)
// ---------------------------------------------------------------------------

interface RoutingDecision {
  action: "execute" | "retry" | "complete" | "error";
  storyId?: string;
  error?: string;
}

function routeFromState(stories: StoryState[], log: Logger): RoutingDecision {
  // retry is checked before selected — a story queued for retry takes
  // precedence over a newly selected story.
  const retry = stories.find((s) => s.status === "retry");
  if (retry) {
    log("Routing: retry", { storyId: retry.storyId });
    return { action: "retry", storyId: retry.storyId };
  }

  const selected = stories.find((s) => s.status === "selected");
  if (selected) {
    log("Routing: execute", { storyId: selected.storyId });
    return { action: "execute", storyId: selected.storyId };
  }

  // Terminal states are exactly "done" and "skipped".
  const terminal = new Set(["done", "skipped"]);
  const allTerminal = stories.every((s) => terminal.has(s.status));
  if (allTerminal && stories.length > 0) {
    log("Routing: complete", { total: stories.length });
    return { action: "complete" };
  }

  return {
    action: "error",
    error: "No actionable story state found (orchestrator may have exited without a routing decision)",
  };
}

// ---------------------------------------------------------------------------
// spawnTracked
// ---------------------------------------------------------------------------

/**
 * Owns the web-server lifecycle (register -> track -> spawn -> clear -> complete)
 * for a single subagent invocation.
 *
 * Does not own story status transitions -- those remain in the callers
 * (runStoryExecution, runStoryReexecution).
 *
 * Full DI of spawnSubagent is out of scope: driver.ts is an entry point,
 * exempt from the "no hard-coded dependencies" rule per project conventions.
 */
async function spawnTracked(
  id: string,
  name: string,
  role: string,
  task: SubagentTask,
  dir: string,
  storyId: string | undefined,
  opts: SpawnOptions,
  webServer: WebServerHandle | null,
): Promise<SubagentResult> {
  webServer?.registerAgent({ id, name, dir, role, model: null, parent: null });
  webServer?.trackSubagent(dir, role, storyId);
  const result = await spawnSubagent(task, dir, opts);
  webServer?.clearSubagent();
  webServer?.completeAgent(id);
  return result;
}

// ---------------------------------------------------------------------------
// Phase role mapping
// ---------------------------------------------------------------------------

/** Maps implemented phases to the subagent role that executes them.
 *  Stubs are not listed — they never spawn a subagent. */
const PHASE_ROLE: Partial<Record<EpicPhase, SubagentRole>> = {
  "intake":           "intake",
  "brief-generation": "brief-writer",
};

// ---------------------------------------------------------------------------
// Phase runners
// ---------------------------------------------------------------------------

async function runSimplePhase(
  role: SubagentRole,
  epicDir: string,
  cwd: string,
  extensionPath: string,
  log: Logger,
  webServer: WebServerHandle | null,
  debugMode: boolean,
  phaseInstructions?: string,
): Promise<boolean> {
  const subagentDir = await ensureSubagentDirectory(epicDir, role);
  const opts: SpawnOptions = { cwd, extensionPath, log, webServer: webServer ?? undefined, debugMode };
  const task = (phaseInstructions
    ? { role, epicDir, phaseInstructions }
    : { role, epicDir }) as SubagentTask;
  const result = await spawnTracked(role, role, role, task, subagentDir, undefined, opts, webServer);
  if (result.exitCode !== 0) {
    log(`${role} phase failed`, { exitCode: result.exitCode });
    return false;
  }
  return true;
}

async function runPhase(
  phase: EpicPhase,
  epicDir: string,
  cwd: string,
  extensionPath: string,
  log: Logger,
  webServer: WebServerHandle | null,
  debugMode: boolean,
  phaseInstructions?: string,
): Promise<boolean> {
  const role = PHASE_ROLE[phase];
  if (!role) {
    // Should never happen — isStubPhase() guards this in the loop above.
    throw new Error(`No role mapping for implemented phase: ${phase}`);
  }
  return runSimplePhase(role, epicDir, cwd, extensionPath, log, webServer, debugMode, phaseInstructions);
}

// ---------------------------------------------------------------------------
// Story execution helpers (dormant — used when execution phase is implemented)
// ---------------------------------------------------------------------------

async function runStoryExecution(
  epicDir: string,
  cwd: string,
  extensionPath: string,
  storyId: string,
  log: Logger,
  webServer: WebServerHandle | null,
  debugMode: boolean,
): Promise<void> {
  const opts: SpawnOptions = { cwd, extensionPath, log, webServer: webServer ?? undefined, debugMode };

  // 1. Set status to 'planning'.
  const story = await loadStoryState(epicDir, storyId);
  await saveStoryState(epicDir, storyId, { ...story, status: "planning", updatedAt: new Date().toISOString() });

  // 2. Spawn planner.
  const plannerDir = await ensureSubagentDirectory(epicDir, `planner-${storyId}`);
  const plannerId = `planner-${storyId}`;
  const planResult = await spawnTracked(plannerId, `planner-${storyId}`, "planner", { role: "planner", epicDir, storyId }, plannerDir, storyId, opts, webServer);

  if (planResult.exitCode !== 0) {
    // Planner failed — skip executor, proceed directly to post-execution
    // orchestrator so it can make a routing decision (retry or skip).
    log("Planner failed — skipping executor, proceeding to post-execution orchestrator", {
      storyId, exitCode: planResult.exitCode,
    });

    const s2 = await loadStoryState(epicDir, storyId);
    await saveStoryState(epicDir, storyId, { ...s2, status: "verifying", updatedAt: new Date().toISOString() });

    const postDir = await ensureSubagentDirectory(epicDir, `orchestrator-post-${storyId}`);
    const postId = `orchestrator-post-${storyId}`;
    await spawnTracked(postId, `orchestrator-post-${storyId}`, "orchestrator", { role: "orchestrator", epicDir, stepSequence: "post-execution", storyId }, postDir, storyId, opts, webServer);
    return;
  }

  // 3. Set status to 'executing'.
  const s3 = await loadStoryState(epicDir, storyId);
  await saveStoryState(epicDir, storyId, { ...s3, status: "executing", updatedAt: new Date().toISOString() });

  // 4. Spawn executor.
  const execDir = await ensureSubagentDirectory(epicDir, `executor-${storyId}`);
  const execId = `executor-${storyId}`;
  const execResult = await spawnTracked(execId, `executor-${storyId}`, "executor", { role: "executor", epicDir, storyId }, execDir, storyId, opts, webServer);

  if (execResult.exitCode !== 0) {
    log("Executor failed", { storyId, exitCode: execResult.exitCode });
  }

  // 5. Set status to 'verifying'.
  const s4 = await loadStoryState(epicDir, storyId);
  await saveStoryState(epicDir, storyId, { ...s4, status: "verifying", updatedAt: new Date().toISOString() });

  // 6. Spawn orchestrator (post-execution).
  const postDir = await ensureSubagentDirectory(epicDir, `orchestrator-post-${storyId}`);
  const postId = `orchestrator-post-${storyId}`;
  await spawnTracked(postId, `orchestrator-post-${storyId}`, "orchestrator", { role: "orchestrator", epicDir, stepSequence: "post-execution", storyId }, postDir, storyId, opts, webServer);
}

async function runStoryReexecution(
  epicDir: string,
  cwd: string,
  extensionPath: string,
  storyId: string,
  retryCount: number,
  failureContext: string | undefined,
  log: Logger,
  webServer: WebServerHandle | null,
  debugMode: boolean,
): Promise<void> {
  const opts: SpawnOptions = { cwd, extensionPath, log, webServer: webServer ?? undefined, debugMode };

  const execDir = await ensureSubagentDirectory(epicDir, `executor-${storyId}-retry-${retryCount}`);
  const execId = `executor-${storyId}-retry-${retryCount}`;
  // retryContext flows from koan_retry_story's failure_summary into the task
  // manifest, where the executor reads it from step 1 guidance.
  await spawnTracked(execId, `executor-${storyId}-retry-${retryCount}`, "executor", { role: "executor", epicDir, storyId, retryContext: failureContext }, execDir, storyId, opts, webServer);

  const story = await loadStoryState(epicDir, storyId);
  await saveStoryState(epicDir, storyId, { ...story, status: "verifying", updatedAt: new Date().toISOString() });

  const postDir = await ensureSubagentDirectory(epicDir, `orchestrator-post-${storyId}-retry-${retryCount}`);
  const postId = `orchestrator-post-${storyId}-retry-${retryCount}`;
  await spawnTracked(postId, `orchestrator-post-${storyId}-retry-${retryCount}`, "orchestrator", { role: "orchestrator", epicDir, stepSequence: "post-execution", storyId }, postDir, storyId, opts, webServer);
}

async function refreshWebServerStories(epicDir: string, webServer: WebServerHandle): Promise<void> {
  try {
    const stories = await loadAllStoryStates(epicDir);
    webServer.pushStories(stories.map((s) => ({ storyId: s.storyId, status: s.status })));
  } catch {
    // Non-fatal
  }
}

async function runStoryLoop(
  epicDir: string,
  cwd: string,
  extensionPath: string,
  log: Logger,
  webServer: WebServerHandle | null,
  debugMode: boolean,
): Promise<{ success: boolean; summary: string }> {
  {
    // 1. Spawn orchestrator (pre-execution) — selects first story.
    const preDir = await ensureSubagentDirectory(epicDir, "orchestrator-pre");
    const preId = "orchestrator-pre";
    const opts: SpawnOptions = { cwd, extensionPath, log, webServer: webServer ?? undefined, debugMode };
    const preResult = await spawnTracked(preId, "orchestrator-pre", "orchestrator", { role: "orchestrator", epicDir, stepSequence: "pre-execution" }, preDir, undefined, opts, webServer);

    if (preResult.exitCode !== 0) {
      return { success: false, summary: "Pre-execution orchestrator failed" };
    }

    if (webServer) await refreshWebServerStories(epicDir, webServer);

    // 2. Story execution loop — route until terminal state.
    while (true) {
      const stories = await loadAllStoryStates(epicDir);
      webServer?.pushStories(stories.map((s) => ({ storyId: s.storyId, status: s.status })));

      const routing = routeFromState(stories, log);

      switch (routing.action) {
        case "execute": {
          const storyId = routing.storyId as string;
          await runStoryExecution(epicDir, cwd, extensionPath, storyId, log, webServer, debugMode);
          if (webServer) await refreshWebServerStories(epicDir, webServer);
          break;
        }

        case "retry": {
          const storyId = routing.storyId as string;
          const story = stories.find((s) => s.storyId === storyId) as StoryState;

          if (story.retryCount >= story.maxRetries) {
            log("Retry budget exhausted, skipping story", { storyId, retryCount: story.retryCount });
            await saveStoryState(epicDir, storyId, {
              ...story,
              status: "skipped",
              skipReason: `Retry budget exhausted after ${story.retryCount} attempt(s). Last failure: ${story.failureSummary ?? "(none recorded)"}`,
              updatedAt: new Date().toISOString(),
            });
            webServer?.pushNotification(
              `Story ${storyId} skipped after ${story.retryCount} failed attempt(s).`,
              "warning",
            );
            if (webServer) await refreshWebServerStories(epicDir, webServer);
            continue;
          }

          await saveStoryState(epicDir, storyId, {
            ...story,
            status: "executing",
            retryCount: story.retryCount + 1,
            updatedAt: new Date().toISOString(),
          });
          await runStoryReexecution(epicDir, cwd, extensionPath, storyId, story.retryCount + 1, story.failureSummary, log, webServer, debugMode);
          if (webServer) await refreshWebServerStories(epicDir, webServer);
          break;
        }

        case "complete": {
          const done = stories.filter((s) => s.status === "done").length;
          const skipped = stories.filter((s) => s.status === "skipped").length;
          return { success: true, summary: `Epic complete: ${done} done, ${skipped} skipped` };
        }

        case "error":
          return { success: false, summary: routing.error as string };
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Workflow orchestrator helpers
// ---------------------------------------------------------------------------

/** Write {epicDir}/workflow-status.md — a markdown bridge from driver JSON
 *  state to the orchestrator LLM's context. Called before orchestrator spawn.
 *
 *  completedPhase is the single just-completed phase (not a history).
 *  The driver does not maintain a phase history array; the orchestrator
 *  infers prior phases from the artifacts present in epicDir. */
async function writeWorkflowStatus(
  epicDir: string,
  completedPhase: EpicPhase,
  availablePhases: readonly EpicPhase[],
): Promise<void> {
  const artifacts = await listArtifacts(epicDir);
  const lines = [
    "# Workflow Status", "",
    "## Current Position", "",
    `The **${completedPhase}** phase has just completed.`, "",
    "## Available Next Phases", "",
    ...availablePhases.map((p) => `- **${p}** — ${PHASE_DESCRIPTIONS[p]}`),
    "", "## Artifacts Available", "",
    ...artifacts.map((a) => `- \`${a.path}\``),
  ];
  await fs.writeFile(path.join(epicDir, "workflow-status.md"), lines.join("\n"), "utf8");
}

async function runWorkflowOrchestrator(
  completedPhase: EpicPhase,
  availablePhases: readonly EpicPhase[],
  epicDir: string,
  cwd: string,
  extensionPath: string,
  log: Logger,
  webServer: WebServerHandle,
  debugMode: boolean,
): Promise<{ nextPhase: EpicPhase; instructions?: string } | null> {
  await writeWorkflowStatus(epicDir, completedPhase, availablePhases);

  const task: WorkflowOrchestratorTask = {
    role: "workflow-orchestrator",
    epicDir,
    completedPhase,
    availablePhases: availablePhases as EpicPhase[],
  };

  // Timestamp ensures no stale workflow-decision.json from a crashed run
  // is accidentally read on restart.
  const dirLabel = `workflow-orch-${completedPhase}-${Date.now()}`;
  const dir = await ensureSubagentDirectory(epicDir, dirLabel);
  const id = `workflow-orchestrator-${completedPhase}`;
  const opts: SpawnOptions = { cwd, extensionPath, log, webServer, debugMode };
  const result = await spawnTracked(id, id, "workflow-orchestrator", task, dir, undefined, opts, webServer);

  if (result.exitCode !== 0) {
    log("Workflow orchestrator failed", { exitCode: result.exitCode, completedPhase });
    return null;
  }

  const decision = await readWorkflowDecision(dir);
  if (!decision) {
    log("Workflow orchestrator exited without committing a decision", { completedPhase });
    return null;
  }
  if (!isValidTransition(completedPhase, decision.nextPhase as EpicPhase)) {
    log("Workflow orchestrator committed an invalid transition", {
      completedPhase, nextPhase: decision.nextPhase,
    });
    return null;
  }

  return { nextPhase: decision.nextPhase as EpicPhase, instructions: decision.instructions };
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export async function runPipeline(
  epicDir: string,
  cwd: string,
  extensionPath: string,
  log: Logger,
  webServer: WebServerHandle | null,
  opts: { debugMode: boolean } = { debugMode: false },
): Promise<{ success: boolean; summary: string }> {
  const { debugMode } = opts;
  const epicState = await loadEpicState(epicDir);

  // Model config gate — blocks until user confirms model selection in the web UI.
  if (webServer) {
    await webServer.requestModelConfig();
  }

  let phase: EpicPhase = "intake";
  let pendingInstructions: string | undefined;

  while (phase !== "completed") {
    await saveEpicState(epicDir, { ...epicState, phase });
    webServer?.pushPhase(phase);

    if (isStubPhase(phase)) {
      // Stub phases register in the DAG but perform no subagent work.
      // pendingInstructions are carried forward — stubs don't consume them.
      log(`Phase "${phase}" is a placeholder — auto-advancing`, { phase });
    } else {
      const phaseOk = await runPhase(phase, epicDir, cwd, extensionPath, log, webServer, debugMode, pendingInstructions);
      // Consumed by the real phase — clear regardless of success.
      pendingInstructions = undefined;
      if (!phaseOk) return { success: false, summary: `Phase "${phase}" failed` };
    }

    const successors = getSuccessorPhases(phase);
    if (successors.length === 0) {
      // Terminal or unknown phase — break and let the completed handler run.
      break;
    }

    if (isAutoAdvance(phase)) {
      // Single successor — unambiguous, advance at zero cost.
      phase = successors[0];
      continue;
    }

    // Multiple successors: requires user direction.
    // In headless mode (no webServer), the orchestrator cannot run because
    // koan_propose_workflow requires requestWorkflowDecision() on the server
    // and the IPC responder is not started. Auto-advance to the recommended
    // (first) successor to preserve CI correctness.
    if (!webServer) {
      log("No web server — auto-advancing to recommended phase (headless mode)", {
        from: phase, to: successors[0],
      });
      phase = successors[0];
      continue;
    }

    // Snapshot the completed phase's activity before spawning the orchestrator.
    // trackSubagent() for the orchestrator will replace the live log buffer;
    // freezeLogs() preserves the phase's final state for the frozen zone in
    // the ActivityFeed.
    webServer.freezeLogs();

    const decision = await runWorkflowOrchestrator(
      phase, successors, epicDir, cwd, extensionPath, log, webServer, debugMode,
    );
    if (!decision) {
      return { success: false, summary: `Workflow orchestrator failed after "${phase}"` };
    }
    phase = decision.nextPhase;
    pendingInstructions = decision.instructions;
  }

  // Save "completed" as the final pipeline state.
  await saveEpicState(epicDir, { ...epicState, phase: "completed" });
  webServer?.pushPhase("completed");

  return { success: true, summary: "Pipeline completed successfully" };
}

