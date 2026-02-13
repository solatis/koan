import { promises as fs } from "node:fs";
import * as path from "node:path";

import type { ExtensionAPI, ExtensionContext } from "@mariozechner/pi-coding-agent";

import {
  draftGuidance,
  verifyGuidance,
  refineGuidance,
  type RefinePromptOptions,
} from "../prompts/context-capture.js";
import { formatStep } from "../prompts/step.js";
import type { ContextCaptureState, PlanInfo, WorkflowState } from "../state.js";
import type { ContextData } from "../types.js";
import { CONTEXT_KEYS } from "../types.js";
import type { ContextToolResult } from "../tools/context-store.js";
import { hookDispatch, unhookDispatch, type WorkflowDispatch } from "../tools/dispatch.js";
import { createLogger, type Logger } from "../../utils/logger.js";
import { checkPermission } from "../tools/registry.js";

const MAX_ATTEMPTS = 3;

interface ValidationResult {
  ok: boolean;
  data?: ContextData;
  errors: string[];
}

export class ContextCapturePhase {
  private readonly state: WorkflowState;
  private readonly pi: ExtensionAPI;
  private readonly log: Logger;
  private readonly dispatch: WorkflowDispatch;
  private readonly onComplete?: (ctx: ExtensionContext) => Promise<string>;

  constructor(
    pi: ExtensionAPI,
    state: WorkflowState,
    dispatch: WorkflowDispatch,
    log?: Logger,
    onComplete?: (ctx: ExtensionContext) => Promise<string>,
  ) {
    this.pi = pi;
    this.state = state;
    this.dispatch = dispatch;
    this.log = log ?? createLogger("Context");
    this.onComplete = onComplete;

    this.registerHandlers();
  }

  async begin(taskDescription: string, plan: PlanInfo, ctx: ExtensionContext): Promise<void> {
    if (this.state.context?.active) {
      ctx.ui.notify("Context capture is already in progress.", "warning");
      return;
    }

    const contextFilePath = path.join(plan.directory, "context.json");
    await fs.rm(contextFilePath, { force: true });

    this.state.phase = "context";
    this.state.context = {
      active: true,
      subPhase: "drafting",
      attempt: 0,
      maxAttempts: MAX_ATTEMPTS,
      taskDescription,
      planId: plan.id,
      planDirectory: plan.directory,
      contextFilePath,
      lastPrompt: null,
      feedback: [],
    } satisfies ContextCaptureState;

    // Hook dispatch slots here (not constructor) because dispatch is
    // shared with plan-design. Each phase hooks when activated (begin()
    // for context-capture, begin() for plan-design). hookDispatch throws
    // if the slot is already occupied (phase hook ownership prevents
    // silent misrouting).
    hookDispatch(this.dispatch, "onCompleteStep", () => this.handleSubPhaseComplete());
    hookDispatch(this.dispatch, "onStoreContext", (p, c) => this.handleContextToolCall(p, c));

    this.log("Starting context capture (draft phase)", { planId: plan.id });
    ctx.ui.notify(`Koan context capture started for plan ${plan.id}.`, "info");

    await this.updatePlanMetadata({
      status: "context",
      context: {
        expectedPath: contextFilePath,
        startedAt: new Date().toISOString(),
      },
    });

    const prompt = formatStep(draftGuidance(taskDescription));
    this.state.context.lastPrompt = prompt;
    this.pi.sendUserMessage(prompt);
  }

  // Advances context capture sub-phase via tool call result.
  // The returned prompt becomes the tool result text that the LLM
  // processes within the same agent loop -- no sendUserMessage needed.
  // Tool result delivery is synchronous regardless of -p mode.
  private handleSubPhaseComplete(): { ok: boolean; prompt?: string; error?: string } {
    const ctx = this.state.context;
    if (!ctx || !this.shouldHandle()) {
      return { ok: false, error: "Context capture is not active." };
    }

    if (ctx.subPhase === "drafting") {
      ctx.subPhase = "verifying";
      const prompt = formatStep(verifyGuidance());
      ctx.lastPrompt = prompt;
      this.log("Draft complete, transition to verify phase (tool call)");
      return { ok: true, prompt };
    }

    if (ctx.subPhase === "verifying") {
      ctx.subPhase = "refining";
      ctx.attempt = 1;
      const prompt = formatStep(
        refineGuidance({
          attempt: 1,
          maxAttempts: ctx.maxAttempts,
          feedback: [],
        }),
      );
      ctx.lastPrompt = prompt;
      this.log("Verify complete, transition to refine phase (tool call)");
      return { ok: true, prompt };
    }

    // Refine phase: koan_store_context handles completion, not this tool.
    return {
      ok: false,
      error: "Refine phase: use koan_store_context to store the context.",
    };
  }

  private registerHandlers(): void {
    this.pi.on("tool_call", async (event) => {
      if (!this.shouldHandle()) return;

      const perm = checkPermission("context-capture", event.toolName);
      if (!perm.allowed) {
        return { block: true, reason: perm.reason };
      }

      const ctx = this.state.context!;

      if (ctx.subPhase === "drafting") {
        if (event.toolName === "koan_store_context") {
          return {
            block: true,
            reason: "Draft phase: explore and draft first, then call koan_complete_step.",
          };
        }
        return undefined;
      }

      if (ctx.subPhase === "verifying") {
        if (event.toolName === "koan_complete_step") {
          return undefined;
        }
        return {
          block: true,
          reason: "Verify phase: review your draft, then call koan_complete_step. No other tools.",
        };
      }

      if (ctx.subPhase === "refining") {
        if (event.toolName === "koan_store_context") {
          return undefined;
        }
        return {
          block: true,
          reason: "Refine phase: call koan_store_context with the verified context.",
        };
      }

      return undefined;
    });
  }

  private shouldHandle(): boolean {
    return Boolean(this.state.context?.active && this.state.phase === "context");
  }

  private async handleContextToolCall(payload: unknown, ctx: ExtensionContext): Promise<ContextToolResult> {
    if (!this.state.context || !this.shouldHandle()) {
      return {
        ok: false,
        message: "Context capture is not active.",
        errors: ["Context capture is not active."],
      };
    }

    const validation = validateContextData(payload);

    if (!validation.ok || !validation.data) {
      const errors = validation.errors.length > 0 ? validation.errors : ["Context validation failed."];
      this.state.context.feedback = errors;
      this.log("Context validation failed", { errors });
      return { ok: false, message: formatErrors(errors), errors };
    }

    const rawText = JSON.stringify(payload, null, 2);
    try {
      await fs.writeFile(this.state.context.contextFilePath, `${rawText}\n`, "utf8");
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.log("Failed to write context file", { error: message });
      return {
        ok: false,
        message: `Failed to write context.json: ${message}`,
        errors: [`Failed to write context.json: ${message}`],
      };
    }

    this.state.context.active = false;
    this.state.context.data = validation.data;
    this.state.context.lastRawContent = rawText;
    this.state.context.feedback = [];
    this.state.phase = "context-complete";
    unhookDispatch(this.dispatch, "onCompleteStep");
    unhookDispatch(this.dispatch, "onStoreContext");

    ctx.ui.notify("Koan context capture complete.", "info");
    this.log("Context capture succeeded", {
      planId: this.state.context.planId,
      attempt: this.state.context.attempt,
    });

    await this.updatePlanMetadata({
      status: "context-complete",
      context: {
        capturedAt: new Date().toISOString(),
        attempt: this.state.context.attempt,
        file: this.state.context.contextFilePath,
      },
    });

    // Trigger completion callback (e.g. architect spawn) synchronously
    // within the tool call. The tool blocks until the callback resolves,
    // preventing the LLM from taking intermediate turns.
    if (this.onComplete) {
      const message = await this.onComplete(ctx);
      return { ok: true, message };
    }
    return { ok: true, message: "Context captured successfully." };
  }

  private async updatePlanMetadata(patch: Record<string, unknown>): Promise<void> {
    const plan = this.state.plan;
    if (!plan) return;

    try {
      let current: Record<string, unknown> = {};
      try {
        const existing = await fs.readFile(plan.metadataPath, "utf8");
        current = JSON.parse(existing);
      } catch {
        current = { id: plan.id, createdAt: plan.createdAt };
      }

      const next = { ...current, ...patch };
      await fs.writeFile(plan.metadataPath, `${JSON.stringify(next, null, 2)}\n`, "utf8");
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.log("Failed to update plan metadata", { error: message });
    }
  }
}

function formatErrors(errors: string[]): string {
  return `Context validation failed:\n${errors.map((e) => `- ${e}`).join("\n")}`;
}

function validateContextData(value: unknown): ValidationResult {
  if (typeof value !== "object" || value === null) {
    return { ok: false, errors: ["Context data must be a JSON object."] };
  }

  const data = value as Record<string, unknown>;
  const errors: string[] = [];
  const result: Record<string, string[]> = {};

  for (const key of CONTEXT_KEYS) {
    const field = data[key];
    if (!Array.isArray(field)) {
      errors.push(`${key} must be an array of strings.`);
      continue;
    }
    if (field.length === 0) {
      errors.push(`${key} must not be empty.`);
      continue;
    }
    const bad = field.findIndex((item) => typeof item !== "string" || item.trim().length === 0);
    if (bad !== -1) {
      errors.push(`${key}[${bad}] must be a non-empty string.`);
      continue;
    }
    result[key] = field.map((s: string) => s.trim());
  }

  if (errors.length > 0) {
    return { ok: false, errors };
  }

  return { ok: true, data: result as unknown as ContextData, errors: [] };
}
