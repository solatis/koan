// Workflow tool registration: koan_complete_step.
//
// This is the single most critical tool in koan. Every subagent workflow depends
// on it being called — it is the mechanism that keeps a pi -p process alive across
// multiple steps. Without it, the LLM would do one turn of work and exit, because
// pi -p processes terminate as soon as the LLM finishes a turn without a tool call.
//
// The workflow pattern: boot prompt → LLM calls koan_complete_step → receives step 1
// instructions → does work → calls koan_complete_step → receives step 2 (or "Phase
// complete.") → repeat. The tool name itself is a call to action: "complete the step."
//
// Tools register once at init; execute callbacks read from the mutable
// RuntimeContext at call time, decoupling static registration from phase routing.

import { Type } from "@sinclair/typebox";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import { createLogger } from "../../utils/logger.js";
import type { RuntimeContext } from "../lib/runtime-context.js";

const log = createLogger("Workflow");

// -- Extracted execute logic --

export async function executeCompleteStep(
  thoughts: string,
  onCompleteStep: ((thoughts: string) => Promise<string | null>) | null,
): Promise<{ content: Array<{ type: "text"; text: string }>; details: undefined }> {
  if (!onCompleteStep) {
    log("koan_complete_step called with no active phase");
    return {
      content: [{ type: "text" as const, text: "No workflow phase is active." }],
      details: undefined,
    };
  }
  const nextPrompt = await onCompleteStep(thoughts);
  return {
    content: [{ type: "text" as const, text: nextPrompt ?? "Phase complete." }],
    details: undefined,
  };
}

// Registers workflow tools. Called once at init in koan.ts,
// before pi's _buildRuntime() snapshot. Tool execute callbacks read
// from the RuntimeContext at call time — the context is mutable,
// the tool list is not.
//
// Why register all tools unconditionally? Flags are unavailable during
// init (getFlag() returns undefined before _buildRuntime() sets flagValues),
// so conditional registration based on role is impossible. Tools registered
// after _buildRuntime() are invisible to the LLM.
export function registerWorkflowTools(
  pi: ExtensionAPI,
  ctx: RuntimeContext,
): void {
  // -- koan_complete_step --
  //
  // INVARIANT: `thoughts` is an ESCAPE HATCH, not a data channel.
  //
  // Many LLMs cannot produce both text output and a tool call in the same
  // response. Without `thoughts`, these models would have no way to do
  // chain-of-thought reasoning (working through lists, chain-of-draft,
  // evaluating items one-by-one) while still calling koan_complete_step to
  // advance the workflow. The parameter gives them a place to write
  // intermediate reasoning. Extended thinking / <thinking> blocks are not
  // sufficient: not all models support them, they aren't visible in audit
  // logs, and some reasoning patterns work better as explicit text the model
  // can reference in subsequent turns.
  //
  // THE RULE: `thoughts` must NEVER be actively used to capture task output.
  // No summaries, no reports, no structured data. Step instructions must NOT
  // say "put your findings/analysis in the `thoughts` parameter." The LLM
  // may fill `thoughts` with whatever it wants — that's fine — but no prompt
  // should instruct it to put specific content there. Task output goes to
  // files in the subagent directory:
  //   - scouts:  {subagentDir}/findings.md
  //   - intake:  {subagentDir}/landscape.md
  //   - others:  as defined by step instructions
  // The driver/parent reads those files after the subagent exits.
  //
  // A 500-char prefix of `thoughts` is captured in the audit projection as
  // `completionSummary` for UI display — this is incidental, not a contract.
  pi.registerTool({
    name: "koan_complete_step",
    label: "Complete current workflow step",
    description: [
      "Signal completion of the current workflow step.",
      "The `thoughts` parameter is for internal chain-of-thought reasoning only — it is NOT captured as task output.",
      "Task output must be written to files in your subagent directory (e.g., findings.md for scouts).",
      "DO NOT call this tool until the step instructions explicitly tell you to.",
    ].join(" "),
    parameters: Type.Object({
      thoughts: Type.Optional(Type.String({
        description: "Internal chain-of-thought reasoning only. NOT task output. Write task output to files in your subagent directory.",
      })),
    }),
    async execute(_toolCallId, params) {
      const thoughts = (params as { thoughts?: string }).thoughts ?? "";
      return executeCompleteStep(thoughts, ctx.onCompleteStep);
    },
  });
}
