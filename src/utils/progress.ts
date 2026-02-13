import { promises as fs } from "node:fs";
import * as crypto from "node:crypto";
import * as path from "node:path";

export interface TrailEntry {
  at: string;
  msg: string;
}

export interface SubagentState {
  role: string;
  phase: string;
  status: "running" | "completed" | "failed";
  current: string;
  updated_at: string;
  trail: TrailEntry[];
}

export async function createSubagentDir(planDir: string, role: string): Promise<string> {
  const hex = crypto.randomBytes(2).toString("hex");
  const dir = path.join(planDir, "subagents", `${role}-${hex}`);
  await fs.mkdir(dir, { recursive: true });
  return dir;
}

export class ProgressReporter {
  private readonly stateFile: string;
  private readonly state: SubagentState;

  constructor(dir: string, role: string, phase: string) {
    this.stateFile = path.join(dir, "state.json");
    this.state = {
      role,
      phase,
      status: "running",
      current: "",
      updated_at: new Date().toISOString(),
      trail: [],
    };
  }

  async update(msg: string): Promise<void> {
    const now = new Date().toISOString();
    this.state.current = msg;
    this.state.updated_at = now;
    this.state.trail.push({ at: now, msg });
    await this.flush();
  }

  async complete(status: "completed" | "failed"): Promise<void> {
    const now = new Date().toISOString();
    this.state.status = status;
    this.state.current = status;
    this.state.updated_at = now;
    this.state.trail.push({ at: now, msg: status });
    await this.flush();
  }

  private async flush(): Promise<void> {
    await fs.writeFile(this.stateFile, JSON.stringify(this.state, null, 2) + "\n");
  }
}

export async function readSubagentState(dir: string): Promise<SubagentState | null> {
  try {
    const raw = await fs.readFile(path.join(dir, "state.json"), "utf8");
    return JSON.parse(raw) as SubagentState;
  } catch {
    return null;
  }
}
