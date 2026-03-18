// Parent-side IPC responder: polls for requests from active subagents,
// handles them, and writes responses back. Runs concurrently with subagent
// process execution and terminates when the provided AbortSignal fires.
//
// Supports two request types:
//   "ask"           → route to web server, write answer back
//   "scout-request" → spawn scouts via pool(), write findings paths back

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
} from "./ipc.js";
// ipc.ts exports ScoutTask (IPC-level: id/role/prompt for the LLM-facing request);
// task.ts also exports ScoutTask (manifest-level: role/epicDir/question/outputFile/investigatorRole).
// Aliased here to avoid shadowing the ipc.ts type used by ScoutIpcFile fields.
import type { ScoutTask as TaskScoutTask } from "./task.js";
import { pool } from "./pool.js";
import { readProjection } from "./audit.js";
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
  spawnScout: (task: TaskScoutTask, scoutSubagentDir: string) => Promise<number>;
}

// Handles a pending ask request: routes to web server, writes response.
async function handleAskRequest(
  subagentDir: string,
  ipc: AskIpcFile,
  webServer: WebServerHandle,
  signal: AbortSignal,
): Promise<void> {
  const { payload } = ipc;
  const questions: AskQuestion[] = payload.questions.map((q) => ({
    id: q.id,
    question: q.question,
    options: q.options.map((o) => ({ label: o.label })),
    multi: q.multi,
    recommended: q.recommended,
  }));

  // Append "Other" option to each question before presenting to the user.
  const withOther: AskQuestion[] = questions.map((q) => ({
    ...q,
    options: [...q.options, { label: OTHER_OPTION }],
  }));

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

  const answers: AskAnswerPayload["answers"] = result.answers.map((a) => {
    const entry: AskAnswerPayload["answers"][number] = {
      id: a.questionId,
      selectedOptions: a.selectedOptions,
    };
    if (a.customInput !== undefined) {
      entry.customInput = a.customInput;
    }
    return entry;
  });

  const response = createAskResponse(ipc.id, { answers });
  // Re-read and validate before writing — idempotence guard against stale requests.
  const current = await readIpcFile(subagentDir);
  if (current !== null && current.type === "ask" && current.response === null && current.id === ipc.id) {
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
  const failures: string[] = [];

  // Compute per-scout directories. Scout dirs live under the epic's subagents/
  // directory so they appear in the standard directory layout.
  const scoutEntries = ipcScouts.map((ipcTask) => {
    const scoutDir = path.join(scoutCtx.epicDir, "subagents", `scout-${ipcTask.id}-${Date.now()}`);
    return { ipcTask, subagentDir: scoutDir };
  });

  // Register scouts with the web server before spawning so the UI shows them
  // immediately rather than waiting for the first audit poll.
  if (webServer) {
    for (const entry of scoutEntries) {
      webServer.registerAgent({
        id: entry.ipcTask.id,
        name: entry.ipcTask.id,
        dir: entry.subagentDir,
        role: "scout",
        model: null,
        parent: scoutCtx.parentRole,
      });
    }
  }

  const taskIds = scoutEntries.map((t) => t.ipcTask.id);
  await pool(
    taskIds,
    4,
    async (taskId) => {
      if (signal.aborted) return { exitCode: 1, stderr: "aborted", subagentDir: "" };

      const entry = scoutEntries.find((t) => t.ipcTask.id === taskId)!;
      await fs.mkdir(entry.subagentDir, { recursive: true });

      // Construct the task manifest for this scout. The IPC-level ipcTask carries
      // id/role/prompt (LLM-facing); the task manifest carries the full SubagentTask
      // fields the scout process needs.
      const scoutTask: TaskScoutTask = {
        role: "scout",
        epicDir: scoutCtx.epicDir,
        question: entry.ipcTask.prompt,
        outputFile: "findings.md",         // relative — ScoutPhase resolves to absolute
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

      const absoluteOutputFile = path.join(entry.subagentDir, scoutTask.outputFile);
      if (succeeded) {
        findings.push(absoluteOutputFile);
      } else {
        failures.push(taskId);
      }

      if (webServer) {
        webServer.completeAgent(taskId);
      }

      return { exitCode, stderr: "", subagentDir: entry.subagentDir };
    },
  );

  // Re-read and validate before writing response — idempotence guard.
  const current = await readIpcFile(subagentDir);
  if (current !== null && current.type === "scout-request" && current.response === null && current.id === id) {
    const updated: ScoutIpcFile = { ...current, response: { findings, failures } };
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
      }
    } catch {
      // Swallow all errors — transient filesystem issues must not abort the parent session.
    }
  }
}
