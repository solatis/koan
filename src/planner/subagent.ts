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
  log?: Logger;
}

export function spawnArchitect(opts: SpawnArchitectOptions): Promise<SubagentResult> {
  const log = opts.log ?? createLogger("Subagent");

  const args = [
    "-p",
    "-e", opts.extensionPath,
    "--koan-role", "architect",
    "--koan-phase", "plan-design",
    "--koan-plan-dir", opts.planDir,
    "--koan-subagent-dir", opts.subagentDir,
    "Begin the plan-design phase.",
  ];

  log("Spawning architect subagent", { planDir: opts.planDir, subagentDir: opts.subagentDir });

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
      log("Architect subagent exited", { exitCode });
      resolve({ exitCode, stderr, subagentDir: opts.subagentDir });
    });

    proc.on("error", (error) => {
      stdoutLog.end();
      stderrLog.end();
      log("Architect subagent spawn error", { error: error.message });
      resolve({ exitCode: 1, stderr: error.message, subagentDir: opts.subagentDir });
    });
  });
}
