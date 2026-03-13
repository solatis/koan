// Debug logger for koan internals. Writes to a log file in the plan directory
// when a log directory has been configured; silent otherwise.
// The Pi TUI captures both stdout and stderr, so neither can be used for debug output.

import { appendFileSync, mkdirSync } from "node:fs";
import * as path from "node:path";

export type Logger = <T extends Record<string, unknown> | undefined>(message: string, details?: T) => void;

const PREFIX = "[koan]";

let logPath: string | null = null;

// Configure the log file location. Call once after the epic directory is created.
// Subsequent createLogger() calls will write to {planDir}/koan.log.
export function setLogDir(planDir: string): void {
  logPath = path.join(planDir, "koan.log");
  try {
    mkdirSync(path.dirname(logPath), { recursive: true });
  } catch {
    // Best effort — directory may already exist.
  }
}

// Create a scoped logger. Returns a function that appends to the configured
// log file. Silent if setLogDir() has not been called.
export function createLogger(scope: string): Logger {
  const label = `${PREFIX} ${scope}`;
  return (message, details) => {
    if (!logPath) return;
    const suffix =
      details !== undefined && Object.keys(details).length > 0
        ? ` ${JSON.stringify(details)}`
        : "";
    try {
      appendFileSync(logPath, `${new Date().toISOString()} ${label}: ${message}${suffix}\n`);
    } catch {
      // Best effort — log file may not be writable yet.
    }
  };
}
