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
  // INVARIANT: `thoughts` is internal chain-of-thought reasoning only.
  // It is NOT captured as task output and must NOT be treated as such.
  // Its purpose: models that cannot mix text output + tool_call in one
  // response (e.g. GPT-5-codex) still express reasoning via this param.
  // Task output is written to files in the subagent directory:
  //   - scouts:  {subagentDir}/findings.md
  //   - intake:  {subagentDir}/context.md
  //   - others:  as defined by step instructions
  // The driver/parent reads those files after the subagent exits.
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
