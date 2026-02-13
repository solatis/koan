import { promises as fs } from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

import type { PlanInfo } from "../planner/state.js";

const KOAN_HOME = path.join(os.homedir(), ".koan");
const PLANS_HOME = path.join(KOAN_HOME, "plans");

function slugify(input: string): string {
  const base = input
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48);

  return base.length > 0 ? base : "plan";
}

function generatePlanId(description: string, now: Date): string {
  const timestamp = now.toISOString().replace(/[-:]/g, "").replace(/\..+/, "");
  const slug = slugify(description);
  return `${timestamp}-${slug}`;
}

async function ensurePlanDirectoryUnique(baseId: string): Promise<{ id: string; directory: string }> {
  let suffix = 0;
  while (true) {
    const candidateId = suffix === 0 ? baseId : `${baseId}-${suffix}`;
    const directory = path.join(PLANS_HOME, candidateId);

    try {
      await fs.mkdir(directory, { recursive: false });
      return { id: candidateId, directory };
    } catch (error) {
      const err = error as NodeJS.ErrnoException;
      if (err.code === "EEXIST") {
        suffix += 1;
        continue;
      }
      throw error;
    }
  }
}

export async function createPlanInfo(description: string, projectCwd: string, now = new Date()): Promise<PlanInfo> {
  await fs.mkdir(PLANS_HOME, { recursive: true });

  const baseId = generatePlanId(description, now);
  const { id, directory } = await ensurePlanDirectoryUnique(baseId);

  const metadataPath = path.join(directory, "metadata.json");

  const plan: PlanInfo = {
    id,
    directory,
    metadataPath,
    createdAt: now.toISOString(),
  };

  const metadata = {
    id: plan.id,
    createdAt: plan.createdAt,
    description,
    status: "created" as const,
    projectCwd,
  };

  await fs.writeFile(metadataPath, `${JSON.stringify(metadata, null, 2)}\n`, "utf8");

  return plan;
}
