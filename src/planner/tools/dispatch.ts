// Workflow tool dispatch for koan.
//
// Workflow tools (koan_next_step, koan_store_context) are registered once
// at init and read from this dispatch at call time.
// Pi snapshots tools during _buildRuntime() -- late registration is
// invisible to the LLM. The dispatch decouples static registration
// from dynamic phase routing.

import { Type } from "@sinclair/typebox";
import type { ExtensionAPI, ExtensionContext } from "@mariozechner/pi-coding-agent";

import { ContextStoreSchema, type ContextToolResult } from "./context-store.js";
import { createLogger } from "../../utils/logger.js";

const log = createLogger("Dispatch");

// -- Result types --

export interface StepResult {
  ok: boolean;
  prompt?: string;
  error?: string;
}

// -- Dispatch --

export interface WorkflowDispatch {
  onNextStep: (() => StepResult) | null;
  onStoreContext:
    | ((payload: unknown, ctx: ExtensionContext) => Promise<ContextToolResult>)
    | null;
}

export function createDispatch(): WorkflowDispatch {
  return { onNextStep: null, onStoreContext: null };
}

// Decouples tool registration (init-time, before _buildRuntime) from
// plan directory creation (runtime, after flags available). Same
// indirection pattern as WorkflowDispatch.
export interface PlanRef {
  dir: string | null;
}

export function createPlanRef(): PlanRef {
  return { dir: null };
}

// Sets a dispatch slot. Throws if the slot is already occupied --
// prevents silent misrouting when two phases attempt to claim
// the same tool.
export function hookDispatch<K extends keyof WorkflowDispatch>(
  dispatch: WorkflowDispatch,
  key: K,
  handler: NonNullable<WorkflowDispatch[K]>,
): void {
  if (dispatch[key] !== null) {
    throw new Error(`dispatch.${String(key)} is already hooked`);
  }
  (dispatch as Record<string, unknown>)[key] = handler;
}

export function unhookDispatch(
  dispatch: WorkflowDispatch,
  key: keyof WorkflowDispatch,
): void {
  (dispatch as Record<string, unknown>)[key] = null;
}

// -- Tool registration --

// Registers workflow tools. Called once at init in koan.ts,
// before pi's _buildRuntime() snapshot. Tool execute callbacks read
// from the dispatch at call time -- the dispatch is mutable, the
// tool list is not.
//
// Why register all tools unconditionally? Flags are unavailable during
// init (getFlag() returns undefined before _buildRuntime() sets flagValues),
// so conditional registration based on role/phase is impossible. Tools
// registered after _buildRuntime() are invisible to the LLM.
export function registerWorkflowTools(
  pi: ExtensionAPI,
  dispatch: WorkflowDispatch,
): void {
  // -- koan_next_step --
  // "DO NOT call until told" creates prohibition/activation pattern
  // with step prompts. Description = default prohibition, step prompt
  // invoke-after = explicit activation.
  pi.registerTool({
    name: "koan_next_step",
    label: "Advance to next workflow step",
    description: [
      "Signal completion of the current workflow step.",
      "DO NOT call this tool until the step instructions explicitly tell you to.",
      "Do the actual work described in each step BEFORE calling this tool.",
    ].join(" "),
    parameters: Type.Object({}),
    async execute() {
      // Two-layer defense: tool_call blocks with descriptive reasons
      // (primary gate), dispatch null checks as fallback. Dispatch check
      // fires only if tool_call handler is bypassed or misconfigured.
      if (!dispatch.onNextStep) {
        throw new Error("No workflow phase is active.");
      }
      const r = dispatch.onNextStep();
      if (!r.ok) {
        throw new Error(r.error ?? "Step transition failed.");
      }
      return {
        content: [{ type: "text" as const, text: r.prompt ?? "Step complete." }],
      };
    },
  });

  // -- koan_store_context --
  pi.registerTool({
    name: "koan_store_context",
    label: "Store planning context",
    description: [
      "Store structured planning context.",
      "DO NOT call this tool until the step instructions explicitly tell you to.",
      "Each field is a string array -- encode structure within strings, not as nested objects.",
    ].join(" "),
    parameters: ContextStoreSchema,
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      if (!dispatch.onStoreContext) {
        throw new Error("Context capture is not active.");
      }
      const r = await dispatch.onStoreContext(params, ctx);
      if (!r.ok) {
        log("Context store rejected", { errors: r.errors });
        throw new Error(r.message);
      }
      log("Context stored");
      return {
        content: [{ type: "text" as const, text: r.message }],
      };
    },
  });
}
