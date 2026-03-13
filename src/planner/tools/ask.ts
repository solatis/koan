// IPC-based tools: koan_ask_question and koan_request_scouts.
// Both tools use file-based IPC to pause subagent execution and communicate
// with the parent session, then resume with the response.
//
// koan_ask_question  — ask the user a question, get answers
// koan_request_scouts — request parallel codebase scouts, get findings paths

import { Type, type Static } from "@sinclair/typebox";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import type { RuntimeContext } from "../lib/runtime-context.js";
import {
  ipcFileExists,
  writeIpcFile,
  readIpcFile,
  deleteIpcFile,
  createAskRequest,
  createScoutRequest,
  type AskAnswerPayload,
  type ScoutTask,
} from "../lib/ipc.js";

// -- Schemas --

const OptionItemSchema = Type.Object({
  label: Type.String({ description: "Display label" }),
});

const QuestionItemSchema = Type.Object({
  id: Type.String({ description: "Question id (e.g. auth, cache, priority)" }),
  question: Type.String({ description: "Question text" }),
  options: Type.Array(OptionItemSchema, {
    description: "Available options. Do not include 'Other'.",
    minItems: 1,
  }),
  multi: Type.Optional(Type.Boolean({ description: "Allow multi-select" })),
  recommended: Type.Optional(
    Type.Number({ description: "0-indexed recommended option. '(Recommended)' is shown automatically." }),
  ),
});

const AskParamsSchema = Type.Object({
  questions: Type.Array(QuestionItemSchema, { description: "Questions to ask", minItems: 1 }),
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

interface QuestionResult {
  id: string;
  question: string;
  options: string[];
  multi: boolean;
  selectedOptions: string[];
  customInput?: string;
}

function formatSelectionForSummary(result: QuestionResult): string {
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

function formatQuestionContext(result: QuestionResult, index: number): string {
  const lines: string[] = [
    `Question ${index + 1} (${result.id})`,
    `Prompt: ${result.question}`,
    "Options:",
    ...result.options.map((o, i) => `  ${i + 1}. ${o}`),
    "Response:",
  ];

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

function buildSessionContent(results: QuestionResult[]): string {
  const summaryLines = results.map((r) => `${r.id}: ${formatSelectionForSummary(r)}`).join("\n");
  const contextBlocks = results.map((r, i) => formatQuestionContext(r, i)).join("\n\n");
  return `User answers:\n${summaryLines}\n\nAnswer context:\n${contextBlocks}`;
}

function buildQuestionResults(
  params: AskParams,
  answers: AskAnswerPayload["answers"],
): QuestionResult[] {
  return params.questions.map((q) => {
    const answer = answers.find((a) => a.id === q.id) ?? { id: q.id, selectedOptions: [] };
    return {
      id: q.id,
      question: q.question,
      options: q.options.map((o) => o.label),
      multi: q.multi ?? false,
      selectedOptions: answer.selectedOptions,
      customInput: answer.customInput,
    };
  });
}

// -- Shared poll helper --

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// -- Tool registration --

const ASK_TOOL_DESCRIPTION = `
Ask the user for clarification when a choice materially affects the outcome.

- Use when multiple valid approaches have different trade-offs.
- Prefer 2-5 concise options.
- Use multi=true when multiple answers are valid.
- Use recommended=<index> (0-indexed) to mark the default option.
- You can ask multiple related questions in one call using questions[].
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

export function registerAskTools(pi: ExtensionAPI, ctx: RuntimeContext): void {
  // -- koan_ask_question --

  pi.registerTool({
    name: "koan_ask_question",
    label: "Ask question",
    description: ASK_TOOL_DESCRIPTION,
    parameters: AskParamsSchema,

    async execute(_toolCallId, params, signal) {
      const askParams = params as AskParams;
      const dir = ctx.subagentDir;

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

      const ipc = createAskRequest(askParams);
      await writeIpcFile(dir, ipc);

      let aborted = false;
      const onAbort = () => { aborted = true; };
      if (signal) signal.addEventListener("abort", onAbort, { once: true });

      type PollResult = "answered" | "cancelled" | "aborted" | "file-gone";
      let pollResult: PollResult = "file-gone";
      let answeredPayload: AskAnswerPayload | null = null;

      try {
        while (!aborted) {
          await sleep(500);
          if (signal?.aborted) { aborted = true; break; }

          const current = await readIpcFile(dir);
          if (current === null) { pollResult = "file-gone"; break; }

          if (current.type === "ask" && current.response !== null && current.response.id === ipc.id) {
            if (current.response.cancelled) {
              pollResult = "cancelled";
            } else {
              pollResult = "answered";
              answeredPayload = current.response.payload;
            }
            break;
          }
        }

        if (aborted) pollResult = "aborted";
      } finally {
        await deleteIpcFile(dir);
      }

      switch (pollResult) {
        case "answered": {
          const results = buildQuestionResults(askParams, answeredPayload?.answers ?? []);
          return {
            content: [{ type: "text" as const, text: buildSessionContent(results) }],
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
          return {
            content: [{ type: "text" as const, text: "The question was cancelled." }],
            details: undefined,
          };
      }
    },
  });

  // -- koan_request_scouts --

  pi.registerTool({
    name: "koan_request_scouts",
    label: "Request codebase scouts",
    description: SCOUTS_TOOL_DESCRIPTION,
    parameters: RequestScoutsSchema,

    async execute(_toolCallId, params, signal) {
      const { scouts } = params as RequestScoutsParams;
      const dir = ctx.subagentDir;

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

      const ipc = createScoutRequest(scouts as ScoutTask[]);
      await writeIpcFile(dir, ipc);

      let aborted = false;
      const onAbort = () => { aborted = true; };
      if (signal) signal.addEventListener("abort", onAbort, { once: true });

      type PollResult = "completed" | "aborted" | "file-gone";
      let pollResult: PollResult = "file-gone";
      let findings: string[] = [];
      let failures: string[] = [];

      try {
        while (!aborted) {
          await sleep(500);
          if (signal?.aborted) { aborted = true; break; }

          const current = await readIpcFile(dir);
          if (current === null) { pollResult = "file-gone"; break; }

          if (current.type === "scout-request" && current.response !== null && current.id === ipc.id) {
            pollResult = "completed";
            findings = current.response.findings;
            failures = current.response.failures;
            break;
          }
        }

        if (aborted) pollResult = "aborted";
      } finally {
        await deleteIpcFile(dir);
      }

      switch (pollResult) {
        case "completed": {
          const lines: string[] = [
            `Scout findings: ${findings.length} completed, ${failures.length} failed.`,
            "",
          ];
          if (findings.length > 0) {
            lines.push("Findings files (read these for codebase context):");
            for (const f of findings) lines.push(`  ${f}`);
          }
          if (failures.length > 0) {
            lines.push(`Failed scouts (non-fatal, proceed without them): ${failures.join(", ")}`);
          }
          return {
            content: [{ type: "text" as const, text: lines.join("\n") }],
            details: undefined,
          };
        }
        case "aborted":
          return {
            content: [{ type: "text" as const, text: "Scout request aborted. Proceed without codebase context." }],
            details: undefined,
          };
        case "file-gone":
          return {
            content: [{ type: "text" as const, text: "Scout request cancelled. Proceed without codebase context." }],
            details: undefined,
          };
      }
    },
  });
}
