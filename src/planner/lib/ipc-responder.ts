// Parent-side IPC responder: polls for requests from active subagents,
// handles them, and writes responses back. Runs concurrently with subagent
// process execution and terminates when the provided AbortSignal fires.
//
// Supports two request types (§11.2.4):
//   "ask"           → render ask UI, write answer back
//   "scout-request" → spawn scouts via pool(), write findings paths back

import { promises as fs } from "node:fs";
import * as path from "node:path";

import type { ExtensionUIContext } from "@mariozechner/pi-coding-agent";

import {
  readIpcFile,
  writeIpcFile,
  createAskResponse,
  createCancelledResponse,
  type AskAnswerPayload,
  type ScoutTask,
  type AskIpcFile,
  type ScoutIpcFile,
} from "./ipc.js";
import { pool } from "./pool.js";
import { askSingleQuestionWithInlineNote } from "../ui/ask/ask-inline-ui.js";
import { askQuestionsWithTabs } from "../ui/ask/ask-tabs-ui.js";
import type { AskQuestion, AskSelection } from "../ui/ask/ask-logic.js";

const POLL_INTERVAL_MS = 300;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// Provided by subagent.ts when starting the IPC responder. Avoids circular
// imports: ipc-responder.ts never imports from subagent.ts.
export interface ScoutSpawnContext {
  epicDir: string;
  // Spawns a single scout; returns exit code.
  spawnScout: (task: ScoutTask, scoutSubagentDir: string, outputFile: string) => Promise<number>;
}

// Handles a pending ask request: renders UI, writes response.
async function handleAskRequest(
  subagentDir: string,
  ipc: AskIpcFile,
  ui: ExtensionUIContext,
  signal: AbortSignal,
): Promise<void> {
  const { payload } = ipc;
  const questions: AskQuestion[] = payload.questions.map((q) => ({
    id: q.id,
    question: q.question,
    options: q.options,
    multi: q.multi,
    recommended: q.recommended,
  }));

  let cancelled = false;
  let answers: AskAnswerPayload["answers"] = [];

  if (questions.length === 1) {
    const q = questions[0];
    const selection = await askSingleQuestionWithInlineNote(ui, {
      question: q.question,
      options: q.options,
      recommended: q.recommended,
    });

    // ask UI components do not accept an AbortSignal — they block until the
    // user interacts even after the subagent exits. Check after return to
    // prevent writing a stale answer to a dead subagent's IPC file.
    if (signal.aborted) {
      const current = await readIpcFile(subagentDir);
      if (current !== null && current.type === "ask" && current.response === null && current.id === ipc.id) {
        await writeIpcFile(subagentDir, { ...current, response: createCancelledResponse(ipc.id) });
      }
      return;
    }

    cancelled = selection.selectedOptions.length === 0 && !selection.customInput;
    if (!cancelled) {
      answers = [{
        id: q.id,
        selectedOptions: selection.selectedOptions,
        customInput: selection.customInput,
      }];
    }
  } else {
    const result = await askQuestionsWithTabs(ui, questions);

    if (signal.aborted) {
      const current = await readIpcFile(subagentDir);
      if (current !== null && current.type === "ask" && current.response === null && current.id === ipc.id) {
        await writeIpcFile(subagentDir, { ...current, response: createCancelledResponse(ipc.id) });
      }
      return;
    }

    cancelled = result.cancelled;
    if (!cancelled) {
      answers = questions.map((q, i) => {
        const sel: AskSelection = result.selections[i] ?? { selectedOptions: [] };
        const entry: AskAnswerPayload["answers"][number] = {
          id: q.id,
          selectedOptions: sel.selectedOptions,
        };
        if (sel.customInput !== undefined) {
          entry.customInput = sel.customInput;
        }
        return entry;
      });
    }
  }

  const response = cancelled
    ? createCancelledResponse(ipc.id)
    : createAskResponse(ipc.id, { answers });

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
  signal: AbortSignal,
): Promise<void> {
  const { scouts, id } = ipc;
  const { epicDir } = scoutCtx;
  const findings: string[] = [];
  const failures: string[] = [];

  // Each scout writes to ${subagentDir}/output.md — output is scoped to the
  // scout's own directory, avoiding collisions. Compute subagentDir once and
  // derive outputFile from it (never call Date.now() twice for the same entry).
  const scoutEntries = scouts.map((task) => {
    const scoutDir = path.join(epicDir, "subagents", `scout-${task.id}-${Date.now()}`);
    return { task, subagentDir: scoutDir, outputFile: path.join(scoutDir, "output.md") };
  });

  const taskIds = scoutEntries.map((t) => t.task.id);
  await pool(
    taskIds,
    4, // up to 4 concurrent scouts
    async (taskId) => {
      if (signal.aborted) return { exitCode: 1, stderr: "aborted", subagentDir: "" };
      const entry = scoutEntries.find((t) => t.task.id === taskId)!;
      await fs.mkdir(entry.subagentDir, { recursive: true });
      const exitCode = await scoutCtx.spawnScout(entry.task, entry.subagentDir, entry.outputFile);
      if (exitCode === 0) {
        findings.push(entry.outputFile);
      } else {
        failures.push(taskId);
      }
      return { exitCode, stderr: "", subagentDir: entry.subagentDir };
    },
  );

  // Write response back to the ipc file.
  const current = await readIpcFile(subagentDir);
  if (current !== null && current.type === "scout-request" && current.response === null && current.id === id) {
    const updated: ScoutIpcFile = { ...current, response: { findings, failures } };
    await writeIpcFile(subagentDir, updated);
  }
}

// Runs the parent-side IPC poll loop for a single subagent directory.
// Routes to ask UI or scout spawning based on request type.
// Terminates when `signal` is aborted. Errors are swallowed — transient
// filesystem issues must not crash the parent session.
export async function runIpcResponder(
  subagentDir: string,
  ui: ExtensionUIContext,
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
        await handleAskRequest(subagentDir, ipc, ui, signal);
      } else if (ipc.type === "scout-request" && scoutContext) {
        await handleScoutRequest(subagentDir, ipc, scoutContext, signal);
      }
      // Unknown type: ignore (forward-compatibility)
    } catch {
      // Swallow all errors — transient filesystem or UI issues must not
      // abort the parent session.
    }
  }
}
