// Package resource path resolution for convention files.
//
// Prompts are hard-coded in TypeScript (see agent-prompts.ts) to avoid runtime
// filesystem dependencies. Conventions remain file-based so subagents can Read
// them directly.

import { existsSync } from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

function findPackageRoot(startDir: string): string {
  let dir = startDir;
  // Supports both source and build layouts.
  // source: <repo>/src/planner/lib
  // build:  <repo>/build/src/planner/lib
  for (let i = 0; i < 8; i++) {
    const conventionsDir = path.join(dir, "resources", "conventions");
    if (existsSync(conventionsDir)) return dir;

    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }

  throw new Error(`Unable to resolve package root from ${startDir}`);
}

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PKG_ROOT = findPackageRoot(HERE);

export const CONVENTIONS_DIR = path.join(PKG_ROOT, "resources/conventions");
