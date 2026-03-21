// Epic pipeline driver — deterministic coordinator for the full epic lifecycle.
// Reads JSON state and exit codes; applies routing rules. Never parses markdown.
// Per AGENTS.md: driver owns .json state; LLMs own .md files.
//
// Spawn pattern used throughout: spawnSubagent(task, subagentDir, opts).
// epicDir is part of the task (written to task.json) rather than SpawnOptions
// because it is subagent configuration, not process infrastructure. SpawnOptions
// holds only what the OS-level spawn needs: cwd, extensionPath, model, webServer.

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
} from "./epic/state.js";
import { spawnSubagent, type SpawnOptions, type SubagentResult } from "./subagent.js";
import type { SubagentTask } from "./lib/task.js";
import type { Logger } from "../utils/logger.js";
import type { StoryState } from "./epic/types.js";
import type { WebServerHandle, ReviewStory } from "./web/server-types.js";

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
// Routing
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
// Phase A helpers
// ---------------------------------------------------------------------------

async function runIntake(
  epicDir: string,
  cwd: string,
  extensionPath: string,
  log: Logger,
  webServer: WebServerHandle | null,
): Promise<boolean> {
  const subagentDir = await ensureSubagentDirectory(epicDir, "intake");
  const opts: SpawnOptions = { cwd, extensionPath, log, webServer: webServer ?? undefined };
  const result = await spawnTracked("intake", "intake", "intake", { role: "intake", epicDir }, subagentDir, undefined, opts, webServer);
  if (result.exitCode !== 0) {
    log("Intake failed", { exitCode: result.exitCode });
    return false;
  }
  return true;
}

async function runDecomposer(
  epicDir: string,
  cwd: string,
  extensionPath: string,
  log: Logger,
  webServer: WebServerHandle | null,
): Promise<boolean> {
  const subagentDir = await ensureSubagentDirectory(epicDir, "decomposer");
  const opts: SpawnOptions = { cwd, extensionPath, log, webServer: webServer ?? undefined };
  const result = await spawnTracked("decomposer", "decomposer", "decomposer", { role: "decomposer", epicDir }, subagentDir, undefined, opts, webServer);
  if (result.exitCode !== 0) {
    log("Decomposer failed", { exitCode: result.exitCode });
    return false;
  }
  return true;
}

// ---------------------------------------------------------------------------
// Phase B helpers
// ---------------------------------------------------------------------------

async function runStoryExecution(
  epicDir: string,
  cwd: string,
  extensionPath: string,
  storyId: string,
  log: Logger,
  webServer: WebServerHandle | null,
): Promise<void> {
  const opts: SpawnOptions = { cwd, extensionPath, log, webServer: webServer ?? undefined };

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
): Promise<void> {
  const opts: SpawnOptions = { cwd, extensionPath, log, webServer: webServer ?? undefined };

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
): Promise<{ success: boolean; summary: string }> {
  {
    // 1. Spawn orchestrator (pre-execution) — selects first story.
    const preDir = await ensureSubagentDirectory(epicDir, "orchestrator-pre");
    const preId = "orchestrator-pre";
    const opts: SpawnOptions = { cwd, extensionPath, log, webServer: webServer ?? undefined };
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
          await runStoryExecution(epicDir, cwd, extensionPath, storyId, log, webServer);
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
          await runStoryReexecution(epicDir, cwd, extensionPath, storyId, story.retryCount + 1, story.failureSummary, log, webServer);
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
// Public API
// ---------------------------------------------------------------------------

export async function runPipeline(
  epicDir: string,
  cwd: string,
  extensionPath: string,
  log: Logger,
  webServer: WebServerHandle | null,
): Promise<{ success: boolean; summary: string }> {
  const epicState = await loadEpicState(epicDir);

  // Model config gate — blocks until user confirms model selection in the web UI.
  if (webServer) {
    await webServer.requestModelConfig();
  }

  // Phase A: Epic Creation.
  webServer?.pushNotification("Starting intake...", "info");
  await saveEpicState(epicDir, { ...epicState, phase: "intake" });
  webServer?.pushPhase("intake");

  const intakeOk = await runIntake(epicDir, cwd, extensionPath, log, webServer);
  if (!intakeOk) return { success: false, summary: "Intake phase failed" };

  const afterIntake = await loadEpicState(epicDir);
  await saveEpicState(epicDir, { ...afterIntake, phase: "decomposition" });
  webServer?.pushPhase("decomposition");

  const decompOk = await runDecomposer(epicDir, cwd, extensionPath, log, webServer);
  if (!decompOk) return { success: false, summary: "Decomposition phase failed" };

  // Discover stories by scanning the filesystem — the decomposer LLM wrote
  // story.md files using the write tool; the driver discovers them here and
  // populates the JSON story list (never asks the LLM to update JSON directly).
  const storyIds = await discoverStoryIds(epicDir);
  log("Discovered story IDs", { count: storyIds.length, ids: storyIds });

  for (const storyId of storyIds) {
    await ensureStoryDirectory(epicDir, storyId);
  }

  const afterDecomp = await loadEpicState(epicDir);
  await saveEpicState(epicDir, { ...afterDecomp, stories: storyIds, phase: "review" });
  webServer?.pushPhase("review");

  if (webServer) {
    const initialStories = await loadAllStoryStates(epicDir);
    webServer.pushStories(initialStories.map((s) => ({ storyId: s.storyId, status: s.status })));
  }

  // Spec review gate — present story sketches for human approval.
  // Auto-approves when no web server is running (CI/headless mode).
  if (webServer && storyIds.length > 0) {
    webServer.pushNotification("Decomposition complete. Review story sketches...", "info");

    const storyData = await Promise.all(storyIds.map(async (id) => {
      const storyPath = path.join(epicDir, "stories", id, "story.md");
      try {
        const raw = await fs.readFile(storyPath, "utf8");
        const title = readStoryTitle(epicDir, id);
        return { raw, title: await title };
      } catch { return { raw: "", title: id }; }
    }));
    const reviewStories: ReviewStory[] = storyIds.map((storyId, i) => ({
      storyId,
      title: storyData[i].title ?? storyId,
      content: storyData[i].raw,
    }));

    const reviewResult = await webServer.requestReview(reviewStories);
    log("Spec review complete", { approved: reviewResult.approved.length, skipped: reviewResult.skipped.length });

    for (const skippedId of reviewResult.skipped) {
      const skippedStory = await loadStoryState(epicDir, skippedId);
      await saveStoryState(epicDir, skippedId, {
        ...skippedStory,
        status: "skipped",
        skipReason: "Removed during spec review",
        updatedAt: new Date().toISOString(),
      });
    }

    const reviewedState = await loadEpicState(epicDir);
    await saveEpicState(epicDir, { ...reviewedState, stories: storyIds });
  } else {
    log("Spec review gate: auto-approving (no web server or no stories)");
  }

  // Phase B: Execution.
  const beforeExec = await loadEpicState(epicDir);
  await saveEpicState(epicDir, { ...beforeExec, phase: "executing" });
  webServer?.pushPhase("executing");

  const result = await runStoryLoop(epicDir, cwd, extensionPath, log, webServer);

  if (result.success) {
    const afterExec = await loadEpicState(epicDir);
    await saveEpicState(epicDir, { ...afterExec, phase: "completed" });
    webServer?.pushPhase("completed");
  }

  return result;
}
