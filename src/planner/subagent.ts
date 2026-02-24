// Subagent spawn helpers. Each public function delegates to spawnSubagent,
// which handles process lifecycle, stdout/stderr routing to disk, and
// exit-code normalization. Spawn errors resolve (not reject) so the caller
// can always read exitCode without try/catch.

import { spawn } from "node:child_process";
import { createWriteStream } from "node:fs";
import * as path from "node:path";

import { createLogger, type Logger } from "../utils/logger.js";

export interface SubagentResult {
  exitCode: number;
  stderr: string;
  subagentDir: string;
}

export interface SpawnArchitectOptions {
  planDir: string;
  subagentDir: string;
  cwd: string;
  extensionPath: string;
  initialPrompt?: string;
  log?: Logger;
}

export interface SpawnArchitectFixOptions {
  planDir: string;
  subagentDir: string;
  cwd: string;
  extensionPath: string;
  fixPhase: string; // e.g. "plan-design"
  log?: Logger;
}

export interface SpawnQRDecomposerOptions {
  planDir: string;
  subagentDir: string;
  cwd: string;
  extensionPath: string;
  log?: Logger;
}

export interface SpawnReviewerOptions {
  planDir: string;
  subagentDir: string;
  cwd: string;
  extensionPath: string;
  itemId: string;
  log?: Logger;
}

// -- Spawn helper --

function spawnSubagent(
  role: string,
  phase: string,
  prompt: string,
  opts: { planDir: string; subagentDir: string; cwd: string; extensionPath: string; extraFlags?: string[] },
  log: Logger,
): Promise<SubagentResult> {
  const args = [
    "-p",
    "-e", opts.extensionPath,
    "--koan-role", role,
    "--koan-phase", phase,
    "--koan-plan-dir", opts.planDir,
    "--koan-subagent-dir", opts.subagentDir,
    ...(opts.extraFlags ?? []),
    prompt,
  ];

  log(`Spawning ${role} subagent`, { planDir: opts.planDir, subagentDir: opts.subagentDir });

  return new Promise((resolve) => {
    const stdoutLog = createWriteStream(path.join(opts.subagentDir, "stdout.log"), { flags: "w" });
    const stderrLog = createWriteStream(path.join(opts.subagentDir, "stderr.log"), { flags: "w" });

    const proc = spawn("pi", args, {
      cwd: opts.cwd,
      shell: false,
      stdio: ["ignore", "pipe", "pipe"],
    });

    let stderr = "";

    proc.stdout.on("data", (data: Buffer) => {
      stdoutLog.write(data);
    });

    proc.stderr.on("data", (data: Buffer) => {
      stderr += data.toString();
      stderrLog.write(data);
    });

    proc.on("close", (code) => {
      stdoutLog.end();
      stderrLog.end();
      const exitCode = code ?? 1;
      log(`${role} subagent exited`, { exitCode });
      resolve({ exitCode, stderr, subagentDir: opts.subagentDir });
    });

    proc.on("error", (error) => {
      stdoutLog.end();
      stderrLog.end();
      log(`${role} subagent spawn error`, { error: error.message });
      resolve({ exitCode: 1, stderr: error.message, subagentDir: opts.subagentDir });
    });
  });
}

// -- Architect spawners --

export function spawnArchitect(opts: SpawnArchitectOptions): Promise<SubagentResult> {
  const log = opts.log ?? createLogger("Subagent");
  return spawnSubagent(
    "architect",
    "plan-design",
    opts.initialPrompt ?? "Begin the plan-design phase.",
    opts,
    log,
  );
}

export function spawnArchitectFix(opts: SpawnArchitectFixOptions): Promise<SubagentResult> {
  const log = opts.log ?? createLogger("Subagent");
  return spawnSubagent(
    "architect",
    "plan-design",
    "Fix the plan based on QR failures.",
    { ...opts, extraFlags: ["--koan-fix", opts.fixPhase] },
    log,
  );
}

// -- QR spawners --

export function spawnQRDecomposer(opts: SpawnQRDecomposerOptions): Promise<SubagentResult> {
  const log = opts.log ?? createLogger("Subagent");
  return spawnSubagent("qr-decomposer", "qr-plan-design", "Begin the QR decompose phase.", opts, log);
}

export function spawnReviewer(opts: SpawnReviewerOptions): Promise<SubagentResult> {
  const log = opts.log ?? createLogger("Subagent");
  return spawnSubagent(
    "reviewer",
    "qr-plan-design",
    "Verify the assigned QR item.",
    { ...opts, extraFlags: ["--koan-qr-item", opts.itemId] },
    log,
  );
}
