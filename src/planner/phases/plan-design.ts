import { promises as fs } from "node:fs";
import * as path from "node:path";

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import { validatePlanDesign, validateRefs } from "../plan/validate.js";
import {
  loadPlanDesignSystemPrompt,
  formatContextForStep1,
  buildPlanDesignSystemPrompt,
  planDesignStepGuidance,
  STEP_NAMES,
} from "../prompts/plan-design.js";
import { formatStep } from "../prompts/step.js";
import type { ContextData } from "../types.js";
import { createLogger, type Logger } from "../../utils/logger.js";
import { ProgressReporter } from "../../utils/progress.js";
import { hookDispatch, unhookDispatch, type WorkflowDispatch, type PlanRef } from "../tools/dispatch.js";
import { checkPermission, PLAN_GETTER_TOOLS } from "../tools/registry.js";

type PlanDesignStep = 1 | 2 | 3 | 4 | 5 | 6;

interface PlanDesignState {
  active: boolean;
  step: PlanDesignStep;
  step1Prompt: string | null;
  contextData: ContextData | null;
  systemPrompt: string | null;
}

export class PlanDesignPhase {
  private readonly pi: ExtensionAPI;
  private readonly planDir: string;
  private readonly log: Logger;
  private readonly state: PlanDesignState;
  private readonly progress: ProgressReporter | null;
  private readonly dispatch: WorkflowDispatch;
  private readonly planRef: PlanRef;

  constructor(pi: ExtensionAPI, config: { planDir: string; subagentDir?: string }, dispatch: WorkflowDispatch, planRef: PlanRef, log?: Logger) {
    this.pi = pi;
    this.planDir = config.planDir;
    this.dispatch = dispatch;
    this.planRef = planRef;
    this.log = log ?? createLogger("PlanDesign");
    this.progress = config.subagentDir
      ? new ProgressReporter(config.subagentDir, "architect", "plan-design")
      : null;

    this.state = {
      active: false,
      step: 1,
      step1Prompt: null,
      contextData: null,
      systemPrompt: null,
    };

    this.registerHandlers();
  }

  async begin(): Promise<void> {
    const contextPath = path.join(this.planDir, "context.json");
    try {
      const raw = await fs.readFile(contextPath, "utf8");
      this.state.contextData = JSON.parse(raw) as ContextData;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.log("Failed to read context.json", { error: message });
      return;
    }

    let basePrompt: string;
    try {
      basePrompt = await loadPlanDesignSystemPrompt();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.log("Failed to load plan-design system prompt", { error: message });
      return;
    }

    const contextXml = formatContextForStep1(this.state.contextData);
    this.state.systemPrompt = buildPlanDesignSystemPrompt(basePrompt);
    this.state.step1Prompt = formatStep(planDesignStepGuidance(1, contextXml));
    this.state.active = true;
    this.state.step = 1;

    // No koan_store_plan tool. Each mutation writes to disk immediately.
    // Step 6 ends with koan_next_step, which runs validation. Removes
    // the two-step 'build then finalize' pattern that caused LLM to skip
    // intermediate tools.
    hookDispatch(this.dispatch, "onNextStep", () => this.handleStepComplete());

    this.log("Starting plan-design workflow", { step: 1 });
    await this.progress?.update(`Step 1/6: ${STEP_NAMES[1]} -- started`);
  }

  private registerHandlers(): void {
    this.pi.on("before_agent_start", () => {
      if (!this.state.active || !this.state.systemPrompt) return undefined;
      return { systemPrompt: this.state.systemPrompt };
    });

    // Step 1 prompt injection. The CLI message is a process trigger --
    // the context event fires before each LLM call and replaces the
    // user message with the actual step 1 instructions. Messages are
    // structuredCloned before reaching this handler (runner.ts:660),
    // so stored history is unaffected. Handler is a no-op once the
    // step advances past 1.
    //
    // Why context event instead of sendUserMessage? Step 1 has no
    // preceding tool call (no tool result to inject prompt into).
    // Context event injects the prompt before the initial LLM call.
    // pi structuredClones messages, so modifications here are isolated.
    this.pi.on("context", (event) => {
      if (!this.state.active) return undefined;
      if (this.state.step !== 1 || !this.state.step1Prompt) return undefined;

      const messages = event.messages.map((m) => {
        if (m.role === "user") {
          return { ...m, content: this.state.step1Prompt! };
        }
        return m;
      });
      return { messages };
    });

    this.pi.on("tool_call", (event) => {
      if (!this.state.active) return undefined;

      const perm = checkPermission("plan-design", event.toolName);
      if (!perm.allowed) {
        return { block: true, reason: perm.reason };
      }

      const step = this.state.step;
      if (step < 6 && !PLAN_GETTER_TOOLS.has(event.toolName) && event.toolName !== "koan_next_step") {
        return {
          block: true,
          reason: `${event.toolName} available in step 6 (current: ${step})`,
        };
      }

      return undefined;
    });

    this.pi.on("turn_end", (event) => {
      if (!this.state.active) return;
    });
  }

  private async handleStepComplete(): Promise<{ ok: boolean; prompt?: string; error?: string }> {
    const prev = this.state.step;

    if (prev === 6) {
      const result = await this.handleFinalize();
      if (!result.ok) {
        return { ok: false, error: result.errors?.join("; ") };
      }
      this.state.active = false;
      unhookDispatch(this.dispatch, "onNextStep");
      this.log("Plan finalized, workflow complete");
      return { ok: true, prompt: "Plan validation passed. Workflow complete." };
    }

    this.state.step = (prev + 1) as PlanDesignStep;
    const nextName = STEP_NAMES[this.state.step];
    const prompt = formatStep(planDesignStepGuidance(this.state.step));

    this.log("Step complete, advancing", { from: prev, to: this.state.step, name: nextName });

    this.progress?.update(`Step ${prev}/6: ${STEP_NAMES[prev]} -- complete`);
    this.progress?.update(`Step ${this.state.step}/6: ${nextName} -- started`);

    return { ok: true, prompt };
  }

  private async handleFinalize(): Promise<{ ok: boolean; errors?: string[] }> {
    const planPath = path.join(this.planDir, "plan.json");
    let plan;
    try {
      const raw = await fs.readFile(planPath, "utf8");
      plan = JSON.parse(raw);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.log("Failed to read plan.json for validation", { error: message });
      return { ok: false, errors: [`Failed to read plan.json: ${message}`] };
    }

    const designValidation = validatePlanDesign(plan);
    if (!designValidation.ok) {
      this.log("Plan design validation failed", { errors: designValidation.errors });
      return { ok: false, errors: designValidation.errors };
    }

    const refValidation = validateRefs(plan);
    if (!refValidation.ok) {
      this.log("Plan reference validation failed", { errors: refValidation.errors });
      return { ok: false, errors: refValidation.errors };
    }

    this.log("Plan validation passed", { path: planPath });
    await this.progress?.update("Step 6/6: " + STEP_NAMES[6] + " -- complete");
    await this.progress?.complete("completed");
    return { ok: true };
  }
}
