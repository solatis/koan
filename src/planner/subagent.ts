// Subagent spawn infrastructure.
//
// A single public function, spawnSubagent(), handles all six roles.
// It writes task.json to the subagent directory before spawning (the
// directory-as-contract invariant: the child reads task.json to discover
// its role and parameters — no structured data flows through CLI flags).
//
// The spawn command carries only what pi needs at the OS level:
//   pi --mode json -p -e {ext} --koan-dir {subagentDir} [--model {model}]
//      [--koan-debug] "{bootPrompt}"
//
// All tools register unconditionally at init. Task-specific content is
// intentionally absent from spawn prompts: it arrives as step 1 guidance
// returned by the first koan_complete_step call, after the calling pattern
// is established.

import { spawn } from "node:child_process";
import { createWriteStream } from "node:fs";
import * as path from "node:path";

import { createLogger, type Logger } from "../utils/logger.js";
import { resolveModelForRole } from "./model-resolver.js";
import { runIpcResponder, type ScoutSpawnContext } from "./lib/ipc-responder.js";
import { writeTaskFile, type SubagentTask, type ScoutTask } from "./lib/task.js";
import { KOAN_DEBUG_FLAG } from "./lib/constants.js";
import type { WebServerHandle } from "./web/server-types.js";

// -- Result type --

export interface SubagentResult {
  exitCode: number;
  stderr: string;
  subagentDir: string;
}

// -- Spawn options --

export interface SpawnOptions {
  cwd: string;
  extensionPath: string;
  /** When true, appends --koan-debug to the child pi args so subagents
   *  receive the debug flag. Non-optional: every construction site must
   *  set it explicitly so TypeScript catches any missed call site. */
  debugMode: boolean;
  modelOverride?: string;
  log?: Logger;
  webServer?: WebServerHandle;
}

// -- Constants --

// Roles that support koan_request_scouts and therefore need a ScoutSpawnContext
// wired into their IPC responder.
const ROLES_WITH_SCOUT_SUPPORT = new Set<SubagentTask["role"]>([
  "intake",
  "decomposer",
  "planner",
]);

// -- Private helpers --

// The entire spawn prompt. Kept to one sentence deliberately: the LLM must
// call koan_complete_step before seeing any task instructions. Putting task
// content here risks text output + immediate exit on weaker models.
function bootPrompt(role: string): string {
  return `You are a koan ${role} agent. Call koan_complete_step to receive your instructions.`;
}

// Builds the CLI args passed to `pi` for a subagent process.
// Exported for unit tests so flag/model argument behavior can be verified
// without spawning a real process.
export function buildSubagentArgs(
  role: SubagentTask["role"],
  subagentDir: string,
  extensionPath: string,
  modelOverride: string | undefined,
  debugMode: boolean,
): string[] {
  return [
    // --mode json makes pi emit structured JSONL on stdout instead of human-
    // readable text. Combined with -p (non-interactive), this is the designed
    // integration surface for external UIs. Pi's own subagent extension uses
    // the identical flag pair — ["--mode", "json", "-p"] — confirming this is
    // the supported composition.
    "--mode", "json",
    "-p",
    "-e", extensionPath,
    "--koan-dir", subagentDir,
    ...(modelOverride ? ["--model", modelOverride] : []),
    ...(debugMode ? ["--" + KOAN_DEBUG_FLAG] : []),
    bootPrompt(role),
  ];
}

// Builds the ScoutSpawnContext injected into the IPC responder. Scouts spawned
// via this context do not receive a web server — they are narrow investigators
// with no user interaction and no nested IPC.
function makeScoutSpawnContext(
  parentRole: string,
  epicDir: string,
  opts: SpawnOptions,
  log: Logger,
): ScoutSpawnContext {
  return {
    epicDir,
    parentRole,
    async spawnScout(task: ScoutTask, scoutSubagentDir: string): Promise<number> {
      const result = await spawnSubagent(task, scoutSubagentDir, {
        cwd: opts.cwd,
        extensionPath: opts.extensionPath,
        debugMode: opts.debugMode,
        // Deliberately no webServer — scouts are narrow investigators.
        log,
      });
      return result.exitCode;
    },
  };
}

// -- Public API --

/**
 * Spawn a koan subagent for the given task.
 *
 * Writes task.json to subagentDir before spawning so the child process can
 * read its role and parameters without relying on CLI flags.
 */
export async function spawnSubagent(
  task: SubagentTask,
  subagentDir: string,
  opts: SpawnOptions,
): Promise<SubagentResult> {
  const log = opts.log ?? createLogger("Subagent");

  await writeTaskFile(subagentDir, task);

  const modelOverride = opts.modelOverride ?? await resolveModelForRole(task.role);

  const scoutContext = ROLES_WITH_SCOUT_SUPPORT.has(task.role)
    ? makeScoutSpawnContext(task.role, task.epicDir, opts, log)
    : undefined;

  const args = buildSubagentArgs(
    task.role,
    subagentDir,
    opts.extensionPath,
    modelOverride,
    opts.debugMode,
  );

  log(`Spawning ${task.role} subagent`, { subagentDir });

  return new Promise((resolve) => {
    const stdoutLog = createWriteStream(path.join(subagentDir, "stdout.log"), { flags: "w" });
    const stderrLog = createWriteStream(path.join(subagentDir, "stderr.log"), { flags: "w" });

    const proc = spawn("pi", args, {
      cwd: opts.cwd,
      shell: false,
      stdio: ["ignore", "pipe", "pipe"],
    });

    // Start IPC responder concurrently when a web server handle is available.
    let abortIpc: (() => void) | undefined;
    if (opts.webServer) {
      const ac = new AbortController();
      abortIpc = () => ac.abort();
      void runIpcResponder(subagentDir, opts.webServer, ac.signal, scoutContext);
    }

    let stderr = "";
    let buffer = "";

    proc.stdout.on("data", (data: Buffer) => {
      // Write raw bytes first — log file receives the full JSONL output
      // regardless of what the parser does. Diagnostics are unaffected.
      stdoutLog.write(data);

      // Accumulate into buffer because a single "data" event may contain
      // a partial line (TCP-style framing — no guarantee of line boundaries).
      buffer += data.toString();

      // Split on newlines. lines[0..n-2] are complete; lines[n-1] may be a
      // partial line — keep it in buffer for the next "data" event.
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";  // trailing partial line (or "" if data ended with \n)

      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const event = JSON.parse(line);
          // Filter to text_delta and thinking_delta. --mode json emits all
          // session events (tool execution, turn boundaries, compaction, etc.).
          // Only these two carry incremental tokens we want to stream.
          // Everything else is handled by the existing state.json polling path.
          if (
            event.type === "message_update" &&
            (event.assistantMessageEvent?.type === "text_delta" ||
             event.assistantMessageEvent?.type === "thinking_delta") &&
            typeof event.assistantMessageEvent.delta === "string"
          ) {
            opts.webServer?.pushTokenDelta(event.assistantMessageEvent.delta);
          }
          // Clear on message_start, NOT message_end. Pipe buffering delivers
          // an entire turn's events in one read(), so clearing on message_end
          // wipes streamingText in the same tick as pushTokenDelta — the
          // browser never renders the text. Clearing on message_start lets
          // thinking text survive through tool execution until the next turn.
          if (
            event.type === "message_start" &&
            event.message?.role === "assistant"
          ) {
            opts.webServer?.clearTokenStream();
          }
        } catch {
          // Malformed line (e.g. stderr bleed or partial JSONL during
          // buffer flush). Skip — the log file has the full bytes.
        }
      }
    });

    proc.stderr.on("data", (data: Buffer) => {
      stderr += data.toString();
      stderrLog.write(data);
    });

    proc.on("close", (code) => {
      abortIpc?.();
      stdoutLog.end();
      stderrLog.end();

      // Flush any partial JSONL line still in the buffer. Under normal
      // operation the buffer is empty at close, but a process killed
      // mid-line (e.g., SIGKILL) would otherwise lose the last event.
      // This must happen before resolve() so the delta arrives before
      // the driver calls clearSubagent() -> pushEvent("subagent-idle").
      if (buffer.trim()) {
        try {
          const event = JSON.parse(buffer);
          if (
            event.type === "message_update" &&
            (event.assistantMessageEvent?.type === "text_delta" ||
             event.assistantMessageEvent?.type === "thinking_delta") &&
            typeof event.assistantMessageEvent.delta === "string"
          ) {
            opts.webServer?.pushTokenDelta(event.assistantMessageEvent.delta);
          }
        } catch {
          // Ignore malformed trailing content — log file has the raw bytes.
        }
      }

      const exitCode = code ?? 1;
      log(`${task.role} subagent exited`, { exitCode });
      resolve({ exitCode, stderr, subagentDir });
    });

    proc.on("error", (error) => {
      abortIpc?.();
      stdoutLog.end();
      stderrLog.end();
      log(`${task.role} subagent spawn error`, { error: error.message });
      resolve({ exitCode: 1, stderr: error.message, subagentDir });
    });
  });
}
