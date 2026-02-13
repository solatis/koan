import { promises as fs } from "node:fs";
import * as path from "node:path";

import type { Plan } from "./types.js";
import { createEmptyPlan } from "./types.js";

export function serializePlan(p: Plan): string {
  return `${JSON.stringify(p, null, 2)}\n`;
}

export async function writePlan(p: Plan, filePath: string): Promise<void> {
  const dir = path.dirname(filePath);
  try {
    await fs.access(dir);
  } catch {
    throw new Error(`Plan directory does not exist: ${dir}`);
  }

  const content = serializePlan(p);
  await fs.writeFile(filePath, content, "utf8");
}

// Atomic write: tmp file + rename. Prevents corrupted plan.json if
// process crashes mid-write.
export async function savePlan(p: Plan, dir: string): Promise<void> {
  const planPath = path.join(dir, "plan.json");
  const tmpPath = path.join(dir, ".plan.json.tmp");
  const content = serializePlan(p);
  await fs.writeFile(tmpPath, content, "utf8");
  await fs.rename(tmpPath, planPath);
}

export async function loadPlan(dir: string): Promise<Plan> {
  const planPath = path.join(dir, "plan.json");
  try {
    const content = await fs.readFile(planPath, "utf8");
    return JSON.parse(content) as Plan;
  } catch (err: unknown) {
    if ((err as NodeJS.ErrnoException).code === "ENOENT") {
      const planId = path.basename(dir);
      return createEmptyPlan(planId);
    }
    throw err;
  }
}
