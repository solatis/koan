// Debug logger for koan internals. Writes to a log file when a plan
// directory is available; silent otherwise. The Pi TUI captures both
// stdout and stderr, so neither can be used for debug output.

import { appendFileSync, mkdirSync } from "node:fs";
import * as path from "node:path";

const prefix = "[koan]";

export type Logger = <T extends Record<string, unknown> | undefined>(message: string, details?: T) => void;

let logPath: string | null = null;

export function setLogDir(planDir: string): void {
  logPath = path.join(planDir, "koan.log");
  try {
    mkdirSync(path.dirname(logPath), { recursive: true });
  } catch {
    // best effort
  }
}

export function createLogger(scope: string): Logger {
  const label = `${prefix} ${scope}`;
  return (message, details) => {
    if (!logPath) return;
    const suffix = details && Object.keys(details).length > 0
      ? ` ${JSON.stringify(details)}`
      : "";
    try {
      appendFileSync(logPath, `${new Date().toISOString()} ${label}: ${message}${suffix}\n`);
    } catch {
      // best effort -- plan dir may not exist yet
    }
  };
}
