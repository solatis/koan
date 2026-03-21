// IPC-based tool: koan_review_artifact.
// Presents a written markdown artifact for human review via file-based IPC,
// pausing subagent execution until the user responds with feedback or accepts.
//
// The review loop is LLM-driven: if the user provides feedback, the LLM revises
// the artifact and invokes this tool again. The tool itself is stateless — it
// reads the artifact, presents it, and returns the user's response verbatim.

import { promises as fs } from "node:fs";

import { Type, type Static } from "@sinclair/typebox";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import type { RuntimeContext } from "../lib/runtime-context.js";
import {
  ipcFileExists,
  writeIpcFile,
  createArtifactReviewRequest,
  pollIpcUntilResponse,
  type ArtifactReviewIpcFile,
} from "../lib/ipc.js";

// -- Schema --

const ReviewArtifactSchema = Type.Object({
  path: Type.String({ description: "File path of the artifact to present for review" }),
  description: Type.Optional(Type.String({ description: "Optional context for the reviewer (e.g. 'This is the epic brief')" })),
});

type ReviewArtifactParams = Static<typeof ReviewArtifactSchema>;

// -- Tool description --

const REVIEW_ARTIFACT_DESCRIPTION = `
Present a written artifact (markdown file) for human review and collect feedback.

Use this after writing an artifact file to get human approval before proceeding.

The user will see the rendered artifact content and can either:
- Accept it — call koan_complete_step after receiving "Accept"
- Provide feedback — revise the artifact and call koan_review_artifact again

Parameters:
- path: the file path of the artifact to review
- description: optional context for the reviewer
`.trim();

// -- Execute logic --

type ToolResult = { content: Array<{ type: "text"; text: string }>; details: undefined };

export async function executeReviewArtifact(
  params: ReviewArtifactParams,
  subagentDir: string | null,
  signal?: AbortSignal | null,
): Promise<ToolResult> {
  const dir = subagentDir;

  if (!dir) {
    return {
      content: [{ type: "text" as const, text: "Error: koan_review_artifact is only available in subagent context." }],
      details: undefined,
    };
  }

  if (await ipcFileExists(dir)) {
    return {
      content: [{ type: "text" as const, text: "Error: An IPC request is already pending." }],
      details: undefined,
    };
  }

  let content: string;
  try {
    content = await fs.readFile(params.path, "utf8");
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return {
      content: [{ type: "text" as const, text: `Error: Could not read artifact at "${params.path}": ${msg}` }],
      details: undefined,
    };
  }

  const ipc = createArtifactReviewRequest({
    artifactPath: params.path,
    content,
    description: params.description,
  });
  await writeIpcFile(dir, ipc);

  const { outcome, ipc: answeredIpc } = await pollIpcUntilResponse(dir, ipc, signal);

  switch (outcome) {
    case "answered": {
      const artifactIpc = answeredIpc as ArtifactReviewIpcFile;
      const feedback = artifactIpc.response?.feedback || "(no feedback)";
      return {
        content: [{ type: "text" as const, text: `User feedback:\n${feedback}` }],
        details: undefined,
      };
    }
    case "aborted":
      return {
        content: [{ type: "text" as const, text: "The review was aborted." }],
        details: undefined,
      };
    case "file-gone":
    default:
      return {
        content: [{ type: "text" as const, text: "The review was cancelled." }],
        details: undefined,
      };
  }
}

// -- Tool registration --

export function registerReviewArtifactTool(pi: ExtensionAPI, ctx: RuntimeContext): void {
  pi.registerTool({
    name: "koan_review_artifact",
    label: "Review artifact",
    description: REVIEW_ARTIFACT_DESCRIPTION,
    parameters: ReviewArtifactSchema,

    async execute(_toolCallId, params, signal) {
      return executeReviewArtifact(params as ReviewArtifactParams, ctx.subagentDir, signal);
    },
  });
}
