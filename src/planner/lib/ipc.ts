// File-based IPC between subagent and parent session.
// A single ipc.json file per subagent directory holds the current request and
// its response. Atomic writes (tmp-rename) prevent partial reads.
//
// IPC protocol supports two message types (§11.2.4):
//   "ask"           — subagent asks the user a question
//   "scout-request" — subagent requests parallel codebase scout spawning

import { promises as fs } from "node:fs";
import * as path from "node:path";
import * as crypto from "node:crypto";

// -- Scout types --

export interface ScoutTask {
  id: string;     // Unique task ID, e.g. "auth-libs"
  role: string;   // Custom role description for the scout
  prompt: string; // What the scout should find
}

export interface ScoutResponse {
  findings: string[];  // File paths to scout output markdown files (absolute)
  failures: string[];  // Scout task IDs that failed (non-fatal)
}

// -- Ask types --

export interface AskQuestionPayload {
  questions: Array<{
    id: string;
    question: string;
    options: Array<{ label: string }>;
    multi?: boolean;
    recommended?: number;
  }>;
}

export interface AskAnswerPayload {
  answers: Array<{
    id: string;
    selectedOptions: string[];
    customInput?: string;
  }>;
}

export interface AskResponse {
  id: string;
  respondedAt: string;
  cancelled: boolean;
  payload: AskAnswerPayload | null;
}

// -- IPC file union --

export interface AskIpcFile {
  type: "ask";
  id: string;
  createdAt: string;
  payload: AskQuestionPayload;
  response: AskResponse | null;
}

export interface ScoutIpcFile {
  type: "scout-request";
  id: string;
  createdAt: string;
  scouts: ScoutTask[];
  response: ScoutResponse | null;
}

export type IpcFile = AskIpcFile | ScoutIpcFile;

// -- File paths --

const IPC_FILE = "ipc.json";
const IPC_TMP_FILE = ".ipc.tmp.json";

// -- I/O helpers --

// Atomic write: .ipc.tmp.json → ipc.json rename.
export async function writeIpcFile(dir: string, data: IpcFile): Promise<void> {
  const tmp = path.join(dir, IPC_TMP_FILE);
  const target = path.join(dir, IPC_FILE);
  await fs.writeFile(tmp, `${JSON.stringify(data, null, 2)}\n`, "utf8");
  await fs.rename(tmp, target);
}

// Returns null on missing file or parse error.
// Treats parse errors as "not ready" to handle partial writes on non-POSIX systems.
export async function readIpcFile(dir: string): Promise<IpcFile | null> {
  try {
    const raw = await fs.readFile(path.join(dir, IPC_FILE), "utf8");
    return JSON.parse(raw) as IpcFile;
  } catch {
    return null;
  }
}

// Fast existence check without parsing.
export async function ipcFileExists(dir: string): Promise<boolean> {
  try {
    await fs.access(path.join(dir, IPC_FILE));
    return true;
  } catch {
    return false;
  }
}

// Removes ipc.json and any lingering .ipc.tmp.json; swallows ENOENT.
export async function deleteIpcFile(dir: string): Promise<void> {
  for (const name of [IPC_FILE, IPC_TMP_FILE]) {
    try {
      await fs.unlink(path.join(dir, name));
    } catch (err: unknown) {
      if ((err as NodeJS.ErrnoException).code !== "ENOENT") throw err;
    }
  }
}

// -- Factory helpers --

export function createAskRequest(payload: AskQuestionPayload): AskIpcFile {
  return {
    type: "ask",
    id: crypto.randomUUID(),
    createdAt: new Date().toISOString(),
    payload,
    response: null,
  };
}

export function createScoutRequest(scouts: ScoutTask[]): ScoutIpcFile {
  return {
    type: "scout-request",
    id: crypto.randomUUID(),
    createdAt: new Date().toISOString(),
    scouts,
    response: null,
  };
}

export function createAskResponse(requestId: string, payload: AskAnswerPayload): AskResponse {
  return {
    id: requestId,
    respondedAt: new Date().toISOString(),
    cancelled: false,
    payload,
  };
}

export function createCancelledResponse(requestId: string): AskResponse {
  return {
    id: requestId,
    respondedAt: new Date().toISOString(),
    cancelled: true,
    payload: null,
  };
}
