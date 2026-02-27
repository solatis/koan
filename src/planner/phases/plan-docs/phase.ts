// Plan-docs phase -- 6-step technical writer workflow producing doc artifacts
// (doc_diff/comments/diagram/readme) in plan.json.

import { promises as fs } from "node:fs";
import * as path from "node:path";

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import { loadAndValidatePlanForPhase } from "../../plan/validate.js";
import {
  loadPlanDocsSystemPrompt,
  formatContextForStep1,
  buildPlanDocsSystemPrompt,
  planDocsStepGuidance,
  STEP_NAMES,
} from "./prompts.js";
import { formatStep } from "../../lib/step.js";
import type { ContextData } from "../../types.js";
import { createLogger, type Logger } from "../../../utils/logger.js";
import { EventLog } from "../../lib/audit.js";
import { hookDispatch, unhookDispatch, type WorkflowDispatch, type PlanRef } from "../../lib/dispatch.js";
import { checkPermission, PLAN_MUTATION_TOOLS } from "../../lib/permissions.js";

type PlanDocsStep = 1 | 2 | 3 | 4 | 5 | 6;

interface PlanDocsState {
  active: boolean;
  step: PlanDocsStep;
  step1Prompt: string | null;
  contextData: ContextData | null;
  systemPrompt: string | null;
}

const TOTAL_STEPS = 6;
const MUTATION_UNLOCK_STEP = 3;

export class PlanDocsPhase {
  private readonly pi: ExtensionAPI;
  private readonly planDir: string;
  private readonly log: Logger;
  private readonly state: PlanDocsState;
  private readonly eventLog: EventLog | undefined;
  private readonly dispatch: WorkflowDispatch;
  private readonly planRef: PlanRef;

  constructor(
    pi: ExtensionAPI,
    config: { planDir: string },
    dispatch: WorkflowDispatch,
    planRef: PlanRef,
    log?: Logger,
    eventLog?: EventLog,
  ) {
    this.pi = pi;
    this.planDir = config.planDir;
    this.dispatch = dispatch;
    this.planRef = planRef;
    this.log = log ?? createLogger("PlanDocs");
    this.eventLog = eventLog;

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
      basePrompt = await loadPlanDocsSystemPrompt();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.log("Failed to load plan-docs system prompt", { error: message });
      return;
    }

    const contextXml = formatContextForStep1(this.state.contextData);
    this.state.systemPrompt = buildPlanDocsSystemPrompt(basePrompt);
    this.state.step1Prompt = formatStep(planDocsStepGuidance(1, contextXml));
    this.state.active = true;
    this.state.step = 1;
    this.planRef.dir = this.planDir;

    hookDispatch(this.dispatch, "onCompleteStep", () => this.handleStepComplete());

    this.log("Starting plan-docs workflow", { step: 1 });
    await this.eventLog?.emitPhaseStart(TOTAL_STEPS);
    await this.eventLog?.emitStepTransition(1, STEP_NAMES[1], TOTAL_STEPS);
  }

  private registerHandlers(): void {
    this.pi.on("before_agent_start", () => {
      if (!this.state.active || !this.state.systemPrompt) return undefined;
      return { systemPrompt: this.state.systemPrompt };
    });

    this.pi.on("context", (event) => {
      if (!this.state.active) return undefined;
      if (this.state.step !== 1 || !this.state.step1Prompt) return undefined;

      const messages = event.messages.map((m) => {
        if (m.role === "user") return { ...m, content: this.state.step1Prompt! };
        return m;
      });
      return { messages };
    });

    this.pi.on("tool_call", (event) => {
      if (!this.state.active) return undefined;

      const perm = checkPermission("plan-docs", event.toolName);
      if (!perm.allowed) return { block: true, reason: perm.reason };

      if (this.state.step < MUTATION_UNLOCK_STEP && PLAN_MUTATION_TOOLS.has(event.toolName)) {
        return {
          block: true,
          reason: `${event.toolName} available from step ${MUTATION_UNLOCK_STEP} (current: ${this.state.step})`,
        };
      }

      return undefined;
    });
  }

  private async handleStepComplete(): Promise<{ ok: boolean; prompt?: string; error?: string }> {
    const prev = this.state.step;

    if (prev === 6) {
      const result = await this.handleFinalize();
      if (!result.ok) {
        await this.eventLog?.emitPhaseEnd("failed", result.errors?.join("; "));
        return { ok: false, error: result.errors?.join("; ") };
      }

      this.state.active = false;
      unhookDispatch(this.dispatch, "onCompleteStep");
      await this.eventLog?.emitPhaseEnd("completed");
      this.log("Plan-docs finalized, workflow complete");
      return { ok: true, prompt: "Plan-docs validation passed. Workflow complete." };
    }

    this.state.step = (prev + 1) as PlanDocsStep;
    const nextName = STEP_NAMES[this.state.step];
    const prompt = formatStep(planDocsStepGuidance(this.state.step));

    this.log("Step complete, advancing", { from: prev, to: this.state.step, name: nextName });
    await this.eventLog?.emitStepTransition(this.state.step, nextName, TOTAL_STEPS);
    return { ok: true, prompt };
  }

  private async handleFinalize(): Promise<{ ok: boolean; errors?: string[] }> {
    return loadAndValidatePlanForPhase(this.planDir, "plan-docs", this.log);
  }
}
