// Subagent spawn helpers. Each public function delegates to spawnSubagent,
// which handles process lifecycle, stdout/stderr routing to disk, and
// exit-code normalization. Spawn errors resolve (not reject) so the caller
// can always read exitCode without try/catch.

import { spawn } from "node:child_process";
import { createWriteStream } from "node:fs";
import * as path from "node:path";

import { createLogger, type Logger } from "../utils/logger.js";

type WorkPhaseKey = "plan-design" | "plan-code" | "plan-docs";

export interface SubagentResult {
  exitCode: number;
  stderr: string;
  subagentDir: string;
}

export interface SpawnWorkOptions {
  planDir: string;
  subagentDir: string;
  cwd: string;
  extensionPath: string;
  initialPrompt?: string;
  log?: Logger;
}

export interface SpawnFixOptions {
  planDir: string;
  subagentDir: string;
  cwd: string;
  extensionPath: string;
  fixPhase: WorkPhaseKey;
  log?: Logger;
}

export interface SpawnQRDecomposerOptions {
  planDir: string;
  subagentDir: string;
  cwd: string;
  extensionPath: string;
  phase: WorkPhaseKey;
  log?: Logger;
}

export interface SpawnReviewerOptions {
  planDir: string;
  subagentDir: string;
  cwd: string;
  extensionPath: string;
  phase: WorkPhaseKey;
  itemId: string;
  log?: Logger;
}

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

  log(`Spawning ${role} subagent`, { planDir: opts.planDir, subagentDir: opts.subagentDir, phase });

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
      log(`${role} subagent exited`, { exitCode, phase });
      resolve({ exitCode, stderr, subagentDir: opts.subagentDir });
    });

    proc.on("error", (error) => {
      stdoutLog.end();
      stderrLog.end();
      log(`${role} subagent spawn error`, { error: error.message, phase });
      resolve({ exitCode: 1, stderr: error.message, subagentDir: opts.subagentDir });
    });
  });
}

function spawnWork(role: string, phase: WorkPhaseKey, prompt: string, opts: SpawnWorkOptions): Promise<SubagentResult> {
  const log = opts.log ?? createLogger("Subagent");
  return spawnSubagent(role, phase, prompt, opts, log);
}

// -- Planning workers --

export function spawnArchitect(opts: SpawnWorkOptions): Promise<SubagentResult> {
  return spawnWork("architect", "plan-design", opts.initialPrompt ?? "Begin the plan-design phase.", opts);
}

export function spawnDeveloper(opts: SpawnWorkOptions): Promise<SubagentResult> {
  return spawnWork("developer", "plan-code", opts.initialPrompt ?? "Begin the plan-code phase.", opts);
}

export function spawnTechnicalWriter(opts: SpawnWorkOptions): Promise<SubagentResult> {
  return spawnWork("technical-writer", "plan-docs", opts.initialPrompt ?? "Begin the plan-docs phase.", opts);
}

// -- Fix workers --

export function spawnArchitectFix(opts: SpawnFixOptions): Promise<SubagentResult> {
  const log = opts.log ?? createLogger("Subagent");
  return spawnSubagent(
    "architect",
    "plan-design",
    "Fix the plan based on QR failures.",
    { ...opts, extraFlags: ["--koan-fix", opts.fixPhase] },
    log,
  );
}

export function spawnDeveloperFix(opts: SpawnFixOptions): Promise<SubagentResult> {
  const log = opts.log ?? createLogger("Subagent");
  return spawnSubagent(
    "developer",
    "plan-code",
    "Fix plan-code output based on QR failures.",
    { ...opts, extraFlags: ["--koan-fix", opts.fixPhase] },
    log,
  );
}

export function spawnTechnicalWriterFix(opts: SpawnFixOptions): Promise<SubagentResult> {
  const log = opts.log ?? createLogger("Subagent");
  return spawnSubagent(
    "technical-writer",
    "plan-docs",
    "Fix plan-docs output based on QR failures.",
    { ...opts, extraFlags: ["--koan-fix", opts.fixPhase] },
    log,
  );
}

// -- QR workers --

export function spawnQRDecomposer(opts: SpawnQRDecomposerOptions): Promise<SubagentResult> {
  const log = opts.log ?? createLogger("Subagent");
  return spawnSubagent("qr-decomposer", `qr-${opts.phase}`, "Begin the QR decompose phase.", opts, log);
}

export function spawnReviewer(opts: SpawnReviewerOptions): Promise<SubagentResult> {
  const log = opts.log ?? createLogger("Subagent");
  return spawnSubagent(
    "reviewer",
    `qr-${opts.phase}`,
    "Verify the assigned QR item.",
    { ...opts, extraFlags: ["--koan-qr-item", opts.itemId] },
    log,
  );
}
