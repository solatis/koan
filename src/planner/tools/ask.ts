// IPC-based tools: koan_ask_question and koan_request_scouts.
// Both tools use file-based IPC to pause subagent execution and communicate
// with the parent session, then resume with the response.
//
// koan_ask_question  — ask the user a question, get an answer
// koan_request_scouts — request parallel codebase scouts, get findings paths

import { promises as fs } from "node:fs";
import * as path from "node:path";

import { Type, type Static } from "@sinclair/typebox";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import type { RuntimeContext } from "../lib/runtime-context.js";
import {
  ipcFileExists,
  writeIpcFile,
  createAskRequest,
  createScoutRequest,
  pollIpcUntilResponse,
  type AskAnswerPayload,
  type AskIpcFile,
  type ScoutIpcFile,
  type ScoutRequest,
} from "../lib/ipc.js";

// -- Schemas --

const OptionItemSchema = Type.Object({
  label: Type.String({ description: "Display label" }),
});

const AskParamsSchema = Type.Object({
  id: Type.String({ description: "Question id (e.g. auth, cache, priority)" }),
  question: Type.String({ description: "Question text" }),
  context: Type.Optional(Type.String({ description: "Optional background/context to help the user answer." })),
  options: Type.Array(OptionItemSchema, {
    description: "Available options. Do not include 'Other'.",
    minItems: 1,
  }),
  multi: Type.Optional(Type.Boolean({ description: "Allow multi-select" })),
  recommended: Type.Optional(
    Type.Number({ description: "0-indexed recommended option." }),
  ),
});

type AskParams = Static<typeof AskParamsSchema>;

const ScoutTaskSchema = Type.Object({
  id: Type.String({ description: "Scout task ID, e.g. 'auth-libs'" }),
  role: Type.String({ description: "Custom role for the scout, e.g. 'system architect'" }),
  prompt: Type.String({ description: "What to find, e.g. 'Find all auth-related files in src/'" }),
});

const RequestScoutsSchema = Type.Object({
  scouts: Type.Array(ScoutTaskSchema, { description: "Scout tasks to run in parallel", minItems: 1 }),
});

type RequestScoutsParams = Static<typeof RequestScoutsSchema>;

// -- Result formatting (ask) --

interface AskResult {
  id: string;
  question: string;
  context?: string;
  options: string[];
  multi: boolean;
  selectedOptions: string[];
  customInput?: string;
}

function formatSelectionForSummary(result: AskResult): string {
  const hasSelectedOptions = result.selectedOptions.length > 0;
  const hasCustomInput = Boolean(result.customInput);

  if (!hasSelectedOptions && !hasCustomInput) return "(cancelled)";

  if (hasSelectedOptions && hasCustomInput) {
    const selectedPart = result.multi
      ? `[${result.selectedOptions.join(", ")}]`
      : result.selectedOptions[0];
    return `${selectedPart} + Other: "${result.customInput}"`;
  }

  if (hasCustomInput) return `"${result.customInput}"`;
  if (result.multi) return `[${result.selectedOptions.join(", ")}]`;
  return result.selectedOptions[0] ?? "(no selection)";
}

function formatQuestionContext(result: AskResult): string {
  const lines: string[] = [
    `Question (${result.id})`,
    `Prompt: ${result.question}`,
  ];

  if (result.context?.trim()) {
    lines.push("Context:");
    for (const paragraph of result.context.trim().split(/\n\s*\n/u)) {
      lines.push(`  ${paragraph}`);
    }
  }

  lines.push(
    "Options:",
    ...result.options.map((o, i) => `  ${i + 1}. ${o}`),
    "Response:",
  );

  const hasSelectedOptions = result.selectedOptions.length > 0;
  const hasCustomInput = Boolean(result.customInput);

  if (!hasSelectedOptions && !hasCustomInput) {
    lines.push("  Selected: (cancelled)");
    return lines.join("\n");
  }

  if (hasSelectedOptions) {
    const text = result.multi
      ? `[${result.selectedOptions.join(", ")}]`
      : result.selectedOptions[0];
    lines.push(`  Selected: ${text}`);
  }

  if (hasCustomInput) {
    if (!hasSelectedOptions) lines.push("  Selected: Other (type your own)");
    lines.push(`  Custom input: ${result.customInput}`);
  }

  return lines.join("\n");
}

function buildSessionContent(result: AskResult): string {
  return `User answer:\n${result.id}: ${formatSelectionForSummary(result)}\n\nAnswer context:\n${formatQuestionContext(result)}`;
}

function buildQuestionResult(
  params: AskParams,
  answer: AskAnswerPayload | null,
): AskResult {
  const selectedOptions = answer?.id === params.id ? answer.selectedOptions : [];
  const customInput = answer?.id === params.id ? answer.customInput : undefined;

  return {
    id: params.id,
    question: params.question,
    context: params.context,
    options: params.options.map((o) => o.label),
    multi: params.multi ?? false,
    selectedOptions,
    customInput,
  };
}

// -- Tool registration --

const ASK_TOOL_DESCRIPTION = `
Ask the user for clarification when a choice materially affects the outcome.

- Ask exactly one question per call.
- Prefer 2-5 concise options.
- Use multi=true when multiple answers are valid.
- Use recommended=<index> (0-indexed) to mark the default option.
- Optionally include context to give enough background for an informed answer.
- Do NOT include an 'Other' option; UI adds it automatically.
`.trim();

const SCOUTS_TOOL_DESCRIPTION = `
Request parallel codebase scouting. Use when you need to explore specific
areas of the codebase before making decisions or asking questions.

Each scout answers one narrow question and writes findings to a markdown file.
Scouts run in parallel. The tool returns the file paths to read.

- id: unique identifier for this scout task (e.g., "auth-patterns")
- role: the investigator role for the scout (e.g., "security auditor")
- prompt: what to find (e.g., "Find all authentication middleware in src/")
`.trim();

// -- Extracted execute logic --

type ToolResult = { content: Array<{ type: "text"; text: string }>; details: undefined };

export async function executeAskQuestion(
  params: AskParams,
  subagentDir: string | null,
  signal?: AbortSignal | null,
): Promise<ToolResult> {
  const dir = subagentDir;

  if (!dir) {
    return {
      content: [{ type: "text" as const, text: "Error: koan_ask_question is only available in subagent context." }],
      details: undefined,
    };
  }

  if (await ipcFileExists(dir)) {
    return {
      content: [{ type: "text" as const, text: "Error: An IPC request is already pending." }],
      details: undefined,
    };
  }

  const ipc = createAskRequest(params);
  await writeIpcFile(dir, ipc);

  const { outcome, ipc: answeredIpc } = await pollIpcUntilResponse(dir, ipc, signal);
  const answeredPayload: AskAnswerPayload | null =
    outcome === "answered" && answeredIpc?.type === "ask"
      ? (answeredIpc as AskIpcFile).response?.payload ?? null
      : null;

  switch (outcome) {
    case "answered": {
      const result = buildQuestionResult(params, answeredPayload);
      return {
        content: [{ type: "text" as const, text: buildSessionContent(result) }],
        details: undefined,
      };
    }
    case "cancelled":
      return {
        content: [{ type: "text" as const, text: "The user declined to answer. Proceed with your best judgment." }],
        details: undefined,
      };
    case "aborted":
      return {
        content: [{ type: "text" as const, text: "The question was aborted." }],
        details: undefined,
      };
    case "file-gone":
    default:
      return {
        content: [{ type: "text" as const, text: "The question was cancelled." }],
        details: undefined,
      };
  }
}

export async function executeRequestScouts(
  params: RequestScoutsParams,
  subagentDir: string | null,
  signal?: AbortSignal | null,
): Promise<ToolResult> {
  const dir = subagentDir;

  if (!dir) {
    return {
      content: [{ type: "text" as const, text: "Error: koan_request_scouts is only available in subagent context." }],
      details: undefined,
    };
  }

  if (await ipcFileExists(dir)) {
    return {
      content: [{ type: "text" as const, text: "Error: An IPC request is already pending." }],
      details: undefined,
    };
  }

  const ipc = createScoutRequest(params.scouts as ScoutRequest[]);
  await writeIpcFile(dir, ipc);

  const { outcome, ipc: completedIpc } = await pollIpcUntilResponse(dir, ipc, signal);

  switch (outcome) {
    case "completed": {
      const scoutIpc = completedIpc as ScoutIpcFile;
      const findings = scoutIpc.response!.findings;
      const failures = scoutIpc.response!.failures;
      const sections: string[] = [
        `Scout findings: ${findings.length} completed, ${failures.length} failed.`,
        "",
      ];
      for (const f of findings) {
        try {
          const content = await fs.readFile(f, "utf8");
          sections.push(`--- scout: ${path.basename(path.dirname(f))} ---`);
          sections.push(content.trim());
          sections.push("");
        } catch {
          sections.push(`--- scout: ${path.basename(path.dirname(f))} --- (could not read findings)`);
          sections.push("");
        }
      }
      if (failures.length > 0) {
        sections.push(`Failed scouts (non-fatal, proceed without them): ${failures.join(", ")}`);
      }
      return {
        content: [{ type: "text" as const, text: sections.join("\n") }],
        details: undefined,
      };
    }
    case "aborted":
      return {
        content: [{ type: "text" as const, text: "Scout request aborted. Proceed without codebase context." }],
        details: undefined,
      };
    case "file-gone":
    default:
      return {
        content: [{ type: "text" as const, text: "Scout request cancelled. Proceed without codebase context." }],
        details: undefined,
      };
  }
}

// -- Tool registration --

export function registerAskTools(pi: ExtensionAPI, ctx: RuntimeContext): void {
  // -- koan_ask_question --

  pi.registerTool({
    name: "koan_ask_question",
    label: "Ask question",
    description: ASK_TOOL_DESCRIPTION,
    parameters: AskParamsSchema,

    async execute(_toolCallId, params, signal) {
      return executeAskQuestion(params as AskParams, ctx.subagentDir, signal);
    },
  });

  // -- koan_request_scouts --

  pi.registerTool({
    name: "koan_request_scouts",
    label: "Request codebase scouts",
    description: SCOUTS_TOOL_DESCRIPTION,
    parameters: RequestScoutsSchema,

    async execute(_toolCallId, params, signal) {
      return executeRequestScouts(params as RequestScoutsParams, ctx.subagentDir, signal);
    },
  });
}
