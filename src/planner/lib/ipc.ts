// File-based IPC between subagent and parent session.
// A single ipc.json file per subagent directory holds the current request and
// its response. Atomic writes (tmp-rename) prevent partial reads.
//
// IPC protocol supports three message types (§11.2.4):
//   "ask"             — subagent asks the user a question
//   "scout-request"   — subagent requests parallel codebase scout spawning
//   "artifact-review" — subagent presents a written artifact for human review

import { promises as fs } from "node:fs";
import * as path from "node:path";
import * as crypto from "node:crypto";

// -- Scout types --

/** IPC-level scout request: id/role/prompt fields sent by the LLM-facing tool. */
export interface ScoutRequest {
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
  id: string;
  question: string;
  context?: string;
  options: Array<{ label: string }>;
  multi?: boolean;
  recommended?: number;
}

export interface AskAnswerPayload {
  id: string;
  selectedOptions: string[];
  customInput?: string;
}

export interface AskResponse {
  id: string;
  respondedAt: string;
  cancelled: boolean;
  payload: AskAnswerPayload | null;
}

// -- Artifact review types --

export interface ArtifactReviewPayload {
  artifactPath: string;   // relative path within epic dir (e.g., "brief.md")
  content: string;        // raw markdown content of the artifact
  description?: string;   // optional context for the reviewer
}

export interface ArtifactReviewResponse {
  id: string;
  respondedAt: string;
  feedback: string;       // "Accept" or free-form text
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
  scouts: ScoutRequest[];
  response: ScoutResponse | null;
}

export interface ArtifactReviewIpcFile {
  type: "artifact-review";
  id: string;
  createdAt: string;
  payload: ArtifactReviewPayload;
  response: ArtifactReviewResponse | null;
}

export type IpcFile = AskIpcFile | ScoutIpcFile | ArtifactReviewIpcFile;

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

export function createScoutRequest(scouts: ScoutRequest[]): ScoutIpcFile {
  return {
    type: "scout-request",
    id: crypto.randomUUID(),
    createdAt: new Date().toISOString(),
    scouts,
    response: null,
  };
}

export function createArtifactReviewRequest(payload: ArtifactReviewPayload): ArtifactReviewIpcFile {
  return {
    type: "artifact-review",
    id: crypto.randomUUID(),
    createdAt: new Date().toISOString(),
    payload,
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

// -- Poll helper --

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Outcome of a single pollIpcUntilResponse call. */
export type PollOutcome = "answered" | "cancelled" | "aborted" | "file-gone" | "completed";

/** Return value of pollIpcUntilResponse: outcome tag + the IPC file snapshot (if any). */
export interface PollIpcResult {
  outcome: PollOutcome;
  ipc: IpcFile | null;
}

/**
 * Poll ipc.json until a response appears, the signal aborts, or the file vanishes.
 *
 * Extracted because executeAskQuestion and executeRequestScouts share identical
 * poll logic. The finally block guarantees ipc.json deletion even when the signal
 * aborts mid-poll -- without it, a stale ipc.json would block the next tool call.
 */
export async function pollIpcUntilResponse(
  dir: string,
  ipc: IpcFile,
  signal?: AbortSignal | null,
): Promise<PollIpcResult> {
  let aborted = false;
  const onAbort = () => { aborted = true; };
  if (signal) signal.addEventListener("abort", onAbort, { once: true });

  let outcome: PollOutcome = "file-gone";
  let finalIpc: IpcFile | null = null;

  try {
    while (!aborted) {
      await sleep(500);
      if (signal?.aborted) { aborted = true; break; }

      const current = await readIpcFile(dir);
      if (current === null) { outcome = "file-gone"; break; }

      if (current.type === "ask" && current.response !== null && current.response.id === ipc.id) {
        outcome = current.response.cancelled ? "cancelled" : "answered";
        finalIpc = current;
        break;
      }

      if (current.type === "scout-request" && current.response !== null && current.id === ipc.id) {
        outcome = "completed";
        finalIpc = current;
        break;
      }

      if (current.type === "artifact-review" && current.response !== null && current.id === ipc.id) {
        outcome = "answered";
        finalIpc = current;
        break;
      }
    }

    if (aborted) outcome = "aborted";
  } finally {
    await deleteIpcFile(dir);
  }

  return { outcome, ipc: finalIpc };
}
