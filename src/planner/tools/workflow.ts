// Workflow tool registration: koan_complete_step.
// Tools register once at init; execute callbacks read from the mutable
// RuntimeContext at call time, decoupling static registration from phase routing.

import { Type } from "@sinclair/typebox";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import { createLogger } from "../../utils/logger.js";
import type { RuntimeContext } from "../lib/runtime-context.js";

const log = createLogger("Dispatch");

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
  // The `thoughts` parameter captures the model's work output (analysis,
  // review, findings) as a tool parameter instead of as text output.
  // This ensures models that cannot mix text + tool_call in one response
  // (e.g. GPT-5-codex) still advance the workflow reliably.
  pi.registerTool({
    name: "koan_complete_step",
    label: "Complete current workflow step",
    description: [
      "Signal completion of the current workflow step.",
      "Put your analysis, findings, or work output in the `thoughts` parameter.",
      "DO NOT call this tool until the step instructions explicitly tell you to.",
    ].join(" "),
    parameters: Type.Object({
      thoughts: Type.Optional(Type.String({
        description: "Your analysis, findings, or work output for this step.",
      })),
    }),
    async execute(_toolCallId, params) {
      if (!ctx.onCompleteStep) {
        log("koan_complete_step called with no active phase");
        throw new Error("No workflow phase is active.");
      }
      const thoughts = (params as { thoughts?: string }).thoughts ?? "";
      const nextPrompt = await ctx.onCompleteStep(thoughts);
      return {
        content: [{ type: "text" as const, text: nextPrompt ?? "Phase complete." }],
        details: undefined,
      };
    },
  });
}
