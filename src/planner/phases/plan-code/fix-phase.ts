// Plan-code fix phase -- dynamic targeted QR repair workflow.

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import { loadAndValidatePlanForPhase } from "../../plan/validate.js";
import { loadPlanCodeSystemPrompt, buildPlanCodeSystemPrompt } from "./prompts.js";
import {
  fixStepName,
  buildFixSystemPrompt,
  fixStepGuidance,
  formatFailuresXml,
} from "./fix-prompts.js";
import { formatStep } from "../../lib/step.js";
import type { QRItem } from "../../qr/types.js";
import { createLogger, type Logger } from "../../../utils/logger.js";
import { EventLog } from "../../lib/audit.js";
import { hookDispatch, unhookDispatch, type WorkflowDispatch, type PlanRef } from "../../lib/dispatch.js";
import { checkPermission, PLAN_MUTATION_TOOLS } from "../../lib/permissions.js";

interface FixState {
  active: boolean;
  step: number;
  step1Prompt: string | null;
  systemPrompt: string | null;
}

export class PlanCodeFixPhase {
  private readonly pi: ExtensionAPI;
  private readonly planDir: string;
  private readonly failures: ReadonlyArray<QRItem>;
  private readonly log: Logger;
  private readonly state: FixState;
  private readonly eventLog: EventLog | undefined;
  private readonly dispatch: WorkflowDispatch;
  private readonly planRef: PlanRef;

  constructor(
    pi: ExtensionAPI,
    config: { planDir: string; failures: QRItem[] },
    dispatch: WorkflowDispatch,
    planRef: PlanRef,
    log?: Logger,
    eventLog?: EventLog,
  ) {
    this.pi = pi;
    this.planDir = config.planDir;
    this.failures = config.failures;
    this.dispatch = dispatch;
    this.planRef = planRef;
    this.log = log ?? createLogger("PlanCodeFix");
    this.eventLog = eventLog;

    this.state = {
      active: false,
      step: 1,
      step1Prompt: null,
      systemPrompt: null,
    };

    this.registerHandlers();
  }

  private get totalSteps(): number {
    return 2 + this.failures.length;
  }

  async begin(): Promise<void> {
    let basePrompt: string;
    try {
      basePrompt = await loadPlanCodeSystemPrompt();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.log("Fix phase aborted: cannot load system prompt", { error: message });
      return;
    }

    const failuresXml = formatFailuresXml(this.failures);
    const totalSteps = this.totalSteps;
    this.state.systemPrompt = buildFixSystemPrompt(
      buildPlanCodeSystemPrompt(basePrompt),
      this.failures.length,
      totalSteps,
    );
    this.state.step1Prompt = formatStep(fixStepGuidance(1, totalSteps, { allFailuresXml: failuresXml }));
    this.state.active = true;
    this.state.step = 1;
    this.planRef.dir = this.planDir;

    hookDispatch(this.dispatch, "onCompleteStep", () => this.handleStepComplete());

    this.log("Starting plan-code fix workflow", { step: 1, totalSteps, failureCount: this.failures.length });
    await this.eventLog?.emitPhaseStart(totalSteps);
    await this.eventLog?.emitStepTransition(1, fixStepName(1, totalSteps), totalSteps);
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

      const perm = checkPermission("plan-code", event.toolName);
      if (!perm.allowed) return { block: true, reason: perm.reason };

      const step = this.state.step;
      const total = this.totalSteps;
      const inFixRange = step >= 2 && step < total;
      if (!inFixRange && PLAN_MUTATION_TOOLS.has(event.toolName)) {
        return {
          block: true,
          reason: `${event.toolName} available in steps 2-${total - 1} (current: ${step})`,
        };
      }

      return undefined;
    });
  }

  private async handleStepComplete(): Promise<{ ok: boolean; prompt?: string; error?: string }> {
    const prev = this.state.step;
    const total = this.totalSteps;

    if (prev === total) {
      const result = await this.handleFinalize();
      if (!result.ok) {
        await this.eventLog?.emitPhaseEnd("failed", result.errors?.join("; "));
        return { ok: false, error: result.errors?.join("; ") };
      }

      this.state.active = false;
      unhookDispatch(this.dispatch, "onCompleteStep");
      await this.eventLog?.emitPhaseEnd("completed");
      this.log("Fix phase complete, plan-code validation passed");
      return { ok: true, prompt: "Fix phase validation passed. Workflow complete." };
    }

    const next = prev + 1;
    this.state.step = next;

    const item = next >= 2 && next < total ? this.failures[next - 2] : undefined;
    const name = fixStepName(next, total, item);
    const prompt = formatStep(fixStepGuidance(next, total, { item }));

    this.log("Fix step complete, advancing", { from: prev, to: next, name });
    await this.eventLog?.emitStepTransition(next, name, total);
    return { ok: true, prompt };
  }

  private async handleFinalize(): Promise<{ ok: boolean; errors?: string[] }> {
    return loadAndValidatePlanForPhase(this.planDir, "plan-code", this.log);
  }
}
