// Subagent task manifest — the input contract for every subagent process.
// Written by the parent to {subagentDir}/task.json before spawn;
// read by the child exactly once at startup via readTaskFile().
//
// This is one of three well-known JSON files in every subagent directory:
//   task.json   — what to do        (parent writes before spawn, child reads once)
//   state.json  — what has been done (child writes continuously, parent polls)
//   ipc.json    — what is needed now (both sides, transient per-request)
//
// The discriminated union on `role` keeps role-specific fields naturally
// nested rather than collapsed into a flat CLI flag namespace. This directly
// prevents the naming collisions the old flag approach produced — e.g., the
// previous `--koan-role` (pipeline role: "scout") vs `--koan-scout-role`
// (investigator persona: "security auditor") collision is impossible here
// because ScoutTask.role and ScoutTask.investigatorRole are distinct typed
// fields on a struct, not adjacent strings in a flat namespace.

import { promises as fs } from "node:fs";
import * as path from "node:path";

import type { SubagentRole, StepSequence } from "../types.js";

// -- Task types --

interface SubagentTaskBase {
  role: SubagentRole;
  epicDir: string;
}

/** Task manifest for intake subagents. */
export interface IntakeTask extends SubagentTaskBase {
  role: "intake";
}

/**
 * Task manifest for scout subagents. Written by the IPC responder when a
 * planning role (intake, decomposer, planner) calls koan_request_scouts.
 */
export interface ScoutTask extends SubagentTaskBase {
  role: "scout";
  /** The narrow investigation question, injected verbatim into step 1 guidance. */
  question: string;
  /**
   * Output path relative to subagentDir (e.g. "findings.md").
   * Stored relative so the manifest is location-independent.
   * Resolved to absolute by dispatch: `path.join(ctx.subagentDir!, task.outputFile)`.
   */
  outputFile: string;
  /** Investigator persona for the scout LLM (e.g. "security auditor", "API analyst"). */
  investigatorRole: string;
}

/** Task manifest for decomposer subagents. */
export interface DecomposerTask extends SubagentTaskBase {
  role: "decomposer";
}

/** Task manifest for orchestrator subagents. */
export interface OrchestratorTask extends SubagentTaskBase {
  role: "orchestrator";
  stepSequence: StepSequence;
  storyId?: string;
}

/** Task manifest for planner subagents. */
export interface PlannerTask extends SubagentTaskBase {
  role: "planner";
  storyId: string;
}

/** Task manifest for executor subagents. */
export interface ExecutorTask extends SubagentTaskBase {
  role: "executor";
  storyId: string;
  /**
   * Failure summary from a previous execution attempt, sourced from the
   * `failure_summary` parameter of `koan_retry_story`. Absent on first run.
   */
  retryContext?: string;
}

// The union is exhaustive over all six roles. TypeScript narrows task.role
// in switch/case so role-specific fields are accessible without casting.
export type SubagentTask =
  | IntakeTask
  | ScoutTask
  | DecomposerTask
  | OrchestratorTask
  | PlannerTask
  | ExecutorTask;

// -- File paths --

const TASK_FILE = "task.json";
const TASK_TMP_FILE = ".task.tmp.json";

// -- I/O --

// Atomically writes task.json to subagentDir (tmp → rename).
// MUST be called before spawn() — the child reads this file at startup and
// throws if it is missing. There is no recovery path if it arrives late.
export async function writeTaskFile(subagentDir: string, task: SubagentTask): Promise<void> {
  const tmp = path.join(subagentDir, TASK_TMP_FILE);
  const target = path.join(subagentDir, TASK_FILE);
  await fs.writeFile(tmp, `${JSON.stringify(task, null, 2)}\n`, "utf8");
  await fs.rename(tmp, target);
}

// Reads and parses task.json from subagentDir.
// Called exactly once, during before_agent_start in koan.ts.
// Throws on missing file or JSON parse error — both indicate a programming
// error in the parent (wrote no file, or wrote malformed JSON), not a
// recoverable runtime condition.
export async function readTaskFile(subagentDir: string): Promise<SubagentTask> {
  const raw = await fs.readFile(path.join(subagentDir, TASK_FILE), "utf8");
  return JSON.parse(raw) as SubagentTask;
}
