// Subagent spawn infrastructure.
//
// A single public function, spawnSubagent(), handles all six roles.
// It writes task.json to the subagent directory before spawning (the
// directory-as-contract invariant: the child reads task.json to discover
// its role and parameters — no structured data flows through CLI flags).
//
// The spawn command carries only what pi needs at the OS level:
//   pi -p -e {ext} --koan-dir {subagentDir} [--model {model}] "{bootPrompt}"
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

  const args = [
    "-p",
    "-e", opts.extensionPath,
    "--koan-dir", subagentDir,
    ...(modelOverride ? ["--model", modelOverride] : []),
    bootPrompt(task.role),
  ];

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

    proc.stdout.on("data", (data: Buffer) => {
      stdoutLog.write(data);
    });

    proc.stderr.on("data", (data: Buffer) => {
      stderr += data.toString();
      stderrLog.write(data);
    });

    proc.on("close", (code) => {
      abortIpc?.();
      stdoutLog.end();
      stderrLog.end();
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
