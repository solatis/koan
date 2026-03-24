// Parent-side IPC responder: polls for requests from active subagents,
// handles them, and writes responses back. Runs concurrently with subagent
// process execution and terminates when the provided AbortSignal fires.
//
// Supports three request types:
//   "ask"             → route to web server, write answer back
//   "scout-request"   → spawn scouts via pool(), write findings paths back
//   "artifact-review" → route to web server, write feedback back

import { promises as fs } from "node:fs";
import * as path from "node:path";

import {
  readIpcFile,
  writeIpcFile,
  createAskResponse,
  createCancelledResponse,
  type AskAnswerPayload,
  type AskIpcFile,
  type ScoutIpcFile,
  type ArtifactReviewIpcFile,
  type ArtifactReviewResponse,
} from "./ipc.js";
import type { ScoutTask } from "./task.js";
import { pool } from "./pool.js";
import { readProjection } from "./audit.js";
import { loadScoutConcurrency } from "../model-config.js";
import type { WebServerHandle, AskQuestion, AnswerResult } from "../web/server-types.js";
import { OTHER_OPTION } from "../web/server-types.js";

const POLL_INTERVAL_MS = 300;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Provided by subagent.ts when starting the IPC responder. Avoids circular
 * imports: ipc-responder.ts never imports from subagent.ts.
 *
 * `spawnScout` does not accept an `outputFile` argument — the output path is
 * part of the task manifest (task.json). The responder writes `outputFile`
 * into the ScoutTask before handing it to `spawnScout`, then resolves the
 * absolute path via `path.join(subagentDir, scoutTask.outputFile)` itself.
 */
export interface ScoutSpawnContext {
  epicDir: string;
  // The role of the subagent that requested scouting (intake, decomposer, planner).
  // Used for UI attribution when registering scouts with the web server.
  parentRole: string;
  // Spawns a single scout; returns exit code.
  spawnScout: (task: ScoutTask, scoutSubagentDir: string) => Promise<number>;
}

// Handles a pending ask request: routes to web server, writes response.
async function handleAskRequest(
  subagentDir: string,
  ipc: AskIpcFile,
  webServer: WebServerHandle,
  signal: AbortSignal,
): Promise<void> {
  const { payload } = ipc;
  const question: AskQuestion = {
    id: payload.id,
    question: payload.question,
    context: payload.context,
    options: payload.options.map((o) => ({ label: o.label })),
    multi: payload.multi,
    recommended: payload.recommended,
  };

  // Append "Other" option before presenting to the user.
  const withOther: AskQuestion = {
    ...question,
    options: [...question.options, { label: OTHER_OPTION }],
  };

  let result: AnswerResult;
  try {
    result = await webServer.requestAnswer(withOther, signal);
  } catch (err: unknown) {
    if (err instanceof Error && (err.name === "AbortError" || signal.aborted)) {
      const current = await readIpcFile(subagentDir);
      if (current !== null && current.type === "ask" && current.response === null && current.id === ipc.id) {
        await writeIpcFile(subagentDir, { ...current, response: createCancelledResponse(ipc.id) });
      }
      return;
    }
    throw err;
  }

  if (result.cancelled) {
    const current = await readIpcFile(subagentDir);
    if (current !== null && current.type === "ask" && current.response === null && current.id === ipc.id) {
      await writeIpcFile(subagentDir, { ...current, response: createCancelledResponse(ipc.id) });
    }
    return;
  }

  const answer: AskAnswerPayload = {
    id: result.answer.questionId,
    selectedOptions: result.answer.selectedOptions,
  };
  if (result.answer.customInput !== undefined) {
    answer.customInput = result.answer.customInput;
  }

  const response = createAskResponse(ipc.id, answer);
  // Re-read and validate before writing — idempotence guard against stale requests.
  const current = await readIpcFile(subagentDir);
  if (current !== null && current.type === "ask" && current.response === null && current.id === ipc.id) {
    await writeIpcFile(subagentDir, { ...current, response });
  }
}

// Handles a pending artifact-review request: routes to web server, writes feedback.
async function handleArtifactReviewRequest(
  subagentDir: string,
  ipc: ArtifactReviewIpcFile,
  webServer: WebServerHandle,
  signal: AbortSignal,
): Promise<void> {
  const { payload } = ipc;

  let feedback: string;
  try {
    const result = await webServer.requestArtifactReview(payload, signal);
    feedback = result.feedback;
  } catch (err: unknown) {
    if (err instanceof Error && (err.name === "AbortError" || signal.aborted)) {
      const current = await readIpcFile(subagentDir);
      if (current !== null && current.type === "artifact-review" && current.response === null && current.id === ipc.id) {
        const cancelledResponse: ArtifactReviewResponse = {
          id: ipc.id,
          respondedAt: new Date().toISOString(),
          feedback: "Review cancelled.",
        };
        await writeIpcFile(subagentDir, { ...current, response: cancelledResponse });
      }
      return;
    }
    throw err;
  }

  const response: ArtifactReviewResponse = {
    id: ipc.id,
    respondedAt: new Date().toISOString(),
    feedback,
  };
  // Re-read and validate before writing — idempotence guard against stale requests.
  const current = await readIpcFile(subagentDir);
  if (current !== null && current.type === "artifact-review" && current.response === null && current.id === ipc.id) {
    await writeIpcFile(subagentDir, { ...current, response });
  }
}

// Handles a pending scout-request: spawns scouts via pool(), writes findings.
async function handleScoutRequest(
  subagentDir: string,
  ipc: ScoutIpcFile,
  scoutCtx: ScoutSpawnContext,
  webServer: WebServerHandle | undefined,
  signal: AbortSignal,
): Promise<void> {
  const { scouts: ipcScouts, id } = ipc;
  const findings: string[] = [];

  // Compute per-scout directories. Scout dirs live under the epic's subagents/
  // directory so they appear in the standard directory layout.
  const scoutEntries = ipcScouts.map((ipcTask) => {
    const scoutDir = path.join(scoutCtx.epicDir, "subagents", `scout-${ipcTask.id}-${Date.now()}`);
    return { ipcTask, subagentDir: scoutDir };
  });

  // Clear finished agents from previous rounds so the UI starts clean.
  // Without this, completed scouts from round N stay in the table when
  // round N+1 begins — a visual leak since no phase transition fires.
  webServer?.evictFinishedAgents();

  // Register scouts with the web server as queued (status: null) so the UI
  // shows them immediately. They transition to "running" when the pool picks
  // them up and the pi process is actually launched.
  if (webServer) {
    for (const entry of scoutEntries) {
      webServer.registerAgent({
        id: entry.ipcTask.id,
        name: entry.ipcTask.id,
        dir: entry.subagentDir,
        role: "scout",
        model: null,
        parent: scoutCtx.parentRole,
        status: null,
      });
    }
  }

  const taskIds = scoutEntries.map((t) => t.ipcTask.id);
  const concurrency = await loadScoutConcurrency();
  const poolResult = await pool(
    taskIds,
    concurrency,
    async (taskId) => {
      if (signal.aborted) return false;

      const entry = scoutEntries.find((t) => t.ipcTask.id === taskId)!;
      webServer?.startAgent(taskId);
      await fs.mkdir(entry.subagentDir, { recursive: true });

      // Construct the task manifest for this scout. The IPC-level ipcTask carries
      // id/role/prompt (LLM-facing); the task manifest carries the full SubagentTask
      // fields the scout process needs.
      const scoutTask: ScoutTask = {
        role: "scout",
        epicDir: scoutCtx.epicDir,
        question: entry.ipcTask.prompt,
        outputFile: "findings.md",         // relative -- ScoutPhase resolves to absolute
        investigatorRole: entry.ipcTask.role,
      };

      const exitCode = await scoutCtx.spawnScout(scoutTask, entry.subagentDir);

      // Derive success from the JSON audit projection, not from file existence.
      // A scout can write a partial findings.md and then crash.
      let succeeded = false;
      if (exitCode === 0) {
        const projection = await readProjection(entry.subagentDir);
        succeeded = projection?.status === "completed";
      }

      if (succeeded) {
        const absoluteOutputFile = path.join(entry.subagentDir, scoutTask.outputFile);
        findings.push(absoluteOutputFile);
      }

      if (webServer) {
        webServer.completeAgent(taskId);
      }

      return succeeded;
    },
  );

  // Re-read and validate before writing response -- idempotence guard.
  const current = await readIpcFile(subagentDir);
  if (current !== null && current.type === "scout-request" && current.response === null && current.id === id) {
    const updated: ScoutIpcFile = { ...current, response: { findings, failures: poolResult.failed } };
    await writeIpcFile(subagentDir, updated);
  }
}

export async function runIpcResponder(
  subagentDir: string,
  webServer: WebServerHandle,
  signal: AbortSignal,
  scoutContext?: ScoutSpawnContext,
): Promise<void> {
  while (!signal.aborted) {
    try {
      await sleep(POLL_INTERVAL_MS);
      if (signal.aborted) break;

      const ipc = await readIpcFile(subagentDir);
      if (ipc === null || ipc.response !== null) continue;

      if (ipc.type === "ask") {
        await handleAskRequest(subagentDir, ipc, webServer, signal);
      } else if (ipc.type === "scout-request" && scoutContext) {
        await handleScoutRequest(subagentDir, ipc, scoutContext, webServer, signal);
      } else if (ipc.type === "artifact-review") {
        await handleArtifactReviewRequest(subagentDir, ipc, webServer, signal);
      }
    } catch {
      // Swallow all errors — transient filesystem issues must not abort the parent session.
    }
  }
}
