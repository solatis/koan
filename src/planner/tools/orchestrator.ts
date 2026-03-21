// Orchestrator tools: four tools for the orchestrator subagent to advance
// story lifecycle state. koan_escalate is eliminated per §11.3.1 — the
// orchestrator uses koan_ask_question for all user communication.
//
// Each tool:
//  1. Validates that the story is in the correct source state (§11.4/§11.12)
//  2. Writes JSON state (for driver polling)
//  3. Writes templated markdown status.md (for LLM reads, §11.5.4)

import { promises as fs } from "node:fs";
import * as path from "node:path";

import { Type } from "@sinclair/typebox";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import type { RuntimeContext } from "../lib/runtime-context.js";
import { loadStoryState, saveStoryState } from "../epic/state.js";
import type { StoryStatus } from "../types.js";

// -- Helpers --

function now(): string {
  return new Date().toISOString();
}

function storyDir(epicDir: string, storyId: string): string {
  return path.join(epicDir, "stories", storyId);
}

async function writeStatusMd(epicDir: string, storyId: string, content: string): Promise<void> {
  const dir = storyDir(epicDir, storyId);
  const target = path.join(dir, "status.md");
  const tmp = path.join(dir, "status.md.tmp");
  await fs.writeFile(tmp, content, "utf8");
  await fs.rename(tmp, target);
}

// §11.5.4 templated status.md format.
function statusMd(
  storyId: string,
  status: StoryStatus,
  lastAction: string,
  verificationSummary: string,
  notes: string,
): string {
  return [
    `# Status: ${status}`,
    "",
    "## Last Action",
    lastAction,
    "",
    "## Verification Summary",
    verificationSummary,
    "",
    "## Notes",
    notes,
    "",
  ].join("\n");
}

function requireEpicDir(ctx: RuntimeContext): string {
  if (!ctx.epicDir) {
    throw new Error("Epic directory is not set. Is this running inside a koan subagent?");
  }
  return ctx.epicDir;
}

// Validates story status against allowed source statuses. Throws on mismatch.
export function assertStatus(storyId: string, current: StoryStatus, allowed: StoryStatus[]): void {
  if (!allowed.includes(current)) {
    const listed = allowed.map((s) => `'${s}'`).join(" or ");
    throw new Error(
      `Cannot transition story '${storyId}': expected status ${listed}, got '${current}'.`,
    );
  }
}

// -- Extracted execute logic --

type ToolResult = { content: Array<{ type: "text"; text: string }>; details: undefined };

export async function executeSelectStory(epicDir: string, storyId: string): Promise<ToolResult> {
  const ts = now();
  const state = await loadStoryState(epicDir, storyId);
  assertStatus(storyId, state.status, ["pending", "retry"]);

  await saveStoryState(epicDir, storyId, { ...state, status: "selected", updatedAt: ts });
  await writeStatusMd(
    epicDir, storyId,
    statusMd(storyId, "selected", `Selected at: ${ts}`, "(pending -- not yet verified)", ""),
  );

  return {
    content: [{ type: "text" as const, text: `Story '${storyId}' selected.` }],
    details: undefined,
  };
}

export async function executeCompleteStory(
  epicDir: string,
  storyId: string,
  verificationSummary?: string,
): Promise<ToolResult> {
  const ts = now();
  const state = await loadStoryState(epicDir, storyId);
  assertStatus(storyId, state.status, ["verifying"]);

  await saveStoryState(epicDir, storyId, { ...state, status: "done", updatedAt: ts });
  await writeStatusMd(
    epicDir, storyId,
    statusMd(
      storyId, "done",
      `Completed at: ${ts}`,
      verificationSummary ?? "All checks passed.",
      "",
    ),
  );

  return {
    content: [{ type: "text" as const, text: `Story '${storyId}' completed.` }],
    details: undefined,
  };
}

export async function executeRetryStory(
  epicDir: string,
  storyId: string,
  failureSummary: string,
): Promise<ToolResult> {
  const ts = now();
  const state = await loadStoryState(epicDir, storyId);
  assertStatus(storyId, state.status, ["verifying"]);

  await saveStoryState(epicDir, storyId, {
    ...state,
    status: "retry",
    updatedAt: ts,
    failureSummary: failureSummary,
  });
  await writeStatusMd(
    epicDir, storyId,
    statusMd(
      storyId, "retry",
      `Queued for retry at: ${ts}`,
      "Failed -- see Notes for details.",
      failureSummary,
    ),
  );

  return {
    content: [{ type: "text" as const, text: `Story '${storyId}' queued for retry.` }],
    details: undefined,
  };
}

export async function executeSkipStory(
  epicDir: string,
  storyId: string,
  reason: string,
): Promise<ToolResult> {
  const ts = now();
  const state = await loadStoryState(epicDir, storyId);
  assertStatus(storyId, state.status, ["pending", "retry"]);

  await saveStoryState(epicDir, storyId, {
    ...state,
    status: "skipped",
    updatedAt: ts,
    skipReason: reason,
  });
  await writeStatusMd(
    epicDir, storyId,
    statusMd(
      storyId, "skipped",
      `Skipped at: ${ts}`,
      "(not executed)",
      reason,
    ),
  );

  return {
    content: [{ type: "text" as const, text: `Story '${storyId}' skipped.` }],
    details: undefined,
  };
}

// -- Tool registration --

export function registerOrchestratorTools(pi: ExtensionAPI, ctx: RuntimeContext): void {
  // -- koan_select_story --
  // Valid source statuses: pending, retry (§11.4)

  pi.registerTool({
    name: "koan_select_story",
    label: "Select story for execution",
    description: "Mark a pending or retried story as selected for execution. Valid only when the story is in 'pending' or 'retry' status.",
    parameters: Type.Object({
      story_id: Type.String({ description: "The story ID to select." }),
    }),
    async execute(_toolCallId, params) {
      const { story_id } = params as { story_id: string };
      return executeSelectStory(requireEpicDir(ctx), story_id);
    },
  });

  // -- koan_complete_story --
  // Valid source status: verifying (§11.4)

  pi.registerTool({
    name: "koan_complete_story",
    label: "Complete story",
    description: "Mark a story as done after verifying all acceptance criteria are met. Only valid when story is in 'verifying' status.",
    parameters: Type.Object({
      story_id: Type.String({ description: "The story ID to mark as done." }),
      verification_summary: Type.Optional(Type.String({
        description: "Summary of verification checks that passed.",
      })),
    }),
    async execute(_toolCallId, params) {
      const { story_id, verification_summary } = params as {
        story_id: string;
        verification_summary?: string;
      };
      return executeCompleteStory(requireEpicDir(ctx), story_id, verification_summary);
    },
  });

  // -- koan_retry_story --
  // Valid source status: verifying (§11.4)

  pi.registerTool({
    name: "koan_retry_story",
    label: "Retry story",
    description: "Mark a story for retry and record why the previous attempt failed. Only valid when story is in 'verifying' status.",
    parameters: Type.Object({
      story_id: Type.String({ description: "The story ID to retry." }),
      failure_summary: Type.String({
        description: "Concrete description of what went wrong. Include failing commands, error messages, and what the executor should do differently.",
      }),
    }),
    async execute(_toolCallId, params) {
      const { story_id, failure_summary } = params as { story_id: string; failure_summary: string };
      return executeRetryStory(requireEpicDir(ctx), story_id, failure_summary);
    },
  });

  // -- koan_skip_story --
  // Valid source statuses: pending, retry (§11.4)

  pi.registerTool({
    name: "koan_skip_story",
    label: "Skip story",
    description: "Mark a pending or retried story as skipped and record the reason. Valid when story is in 'pending' or 'retry' status.",
    parameters: Type.Object({
      story_id: Type.String({ description: "The story ID to skip." }),
      reason: Type.String({ description: "Why this story is being skipped." }),
    }),
    async execute(_toolCallId, params) {
      const { story_id, reason } = params as { story_id: string; reason: string };
      return executeSkipStory(requireEpicDir(ctx), story_id, reason);
    },
  });
}
