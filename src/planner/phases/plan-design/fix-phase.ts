// Plan-design fix phase -- 3-step targeted repair for QR failures.
//
// Separate class from PlanDesignPhase because the workflows diverge:
// initial = 6 steps of exploration then writing (mutations at step 6);
// fix = 3 steps of reading failures then applying targeted fixes
// (mutations at step 2). Conditional branching at every method
// boundary produces worse code than two focused classes.
//
// The fix architect receives QR failures as XML in step 1. It reads
// the current plan state via getter tools, applies minimal mutations
// to address the specific findings, then validates the result. The
// session orchestrator decides whether to re-run QR -- the fix phase
// does not know about iterations or severity escalation.

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import { loadAndValidatePlan } from "../../plan/validate.js";
import {
  loadPlanDesignSystemPrompt,
  buildPlanDesignSystemPrompt,
} from "./prompts.js";
import {
  FIX_STEP_NAMES,
  buildFixSystemPrompt,
  fixStepGuidance,
  formatFailuresXml,
  type FixStep,
} from "./fix-prompts.js";
import { formatStep } from "../../lib/step.js";
import type { QRItem } from "../../qr/types.js";
import { createLogger, type Logger } from "../../../utils/logger.js";
import { EventLog } from "../../lib/audit.js";
import { hookDispatch, unhookDispatch, type WorkflowDispatch, type PlanRef } from "../../lib/dispatch.js";
import { checkPermission, PLAN_MUTATION_TOOLS } from "../../lib/permissions.js";

interface FixPhaseState {
  active: boolean;
  step: FixStep;
  step1Prompt: string | null;
  systemPrompt: string | null;
}

const TOTAL_STEPS = 3;

export class PlanDesignFixPhase {
  private readonly pi: ExtensionAPI;
  private readonly planDir: string;
  private readonly failures: QRItem[];
  private readonly log: Logger;
  private readonly state: FixPhaseState;
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
    this.log = log ?? createLogger("PlanDesignFix");
    this.eventLog = eventLog;

    this.state = {
      active: false,
      step: 1,
      step1Prompt: null,
      systemPrompt: null,
    };

    this.registerHandlers();
  }

  async begin(): Promise<void> {
    let basePrompt: string;
    try {
      basePrompt = await loadPlanDesignSystemPrompt();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.log("Fix phase aborted: cannot load system prompt", { error: message });
      return;
    }

    const failuresXml = formatFailuresXml(this.failures);
    this.state.systemPrompt = buildFixSystemPrompt(
      buildPlanDesignSystemPrompt(basePrompt),
      this.failures.length,
    );
    this.state.step1Prompt = formatStep(fixStepGuidance(1, failuresXml));
    this.state.active = true;
    this.state.step = 1;

    hookDispatch(this.dispatch, "onCompleteStep", () => this.handleStepComplete());

    this.log("Starting plan-design fix workflow", {
      step: 1,
      failureCount: this.failures.length,
    });
    await this.eventLog?.emitPhaseStart(TOTAL_STEPS);
    await this.eventLog?.emitStepTransition(1, FIX_STEP_NAMES[1], TOTAL_STEPS);
  }

  private registerHandlers(): void {
    this.pi.on("before_agent_start", () => {
      if (!this.state.active || !this.state.systemPrompt) return undefined;
      return { systemPrompt: this.state.systemPrompt };
    });

    // Step 1 prompt injection. Same pattern as PlanDesignPhase: the CLI
    // message is a process trigger; the context event replaces it with
    // step 1 instructions before the initial LLM call.
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

      // Step gate: mutation tools are blocked before step 2. Blocklist
      // (not whitelist) so read tools and future pi-native tools pass
      // through after checkPermission approves them.
      const step = this.state.step;
      if (step < 2 && PLAN_MUTATION_TOOLS.has(event.toolName)) {
        return {
          block: true,
          reason: `${event.toolName} available from step 2 (current: ${step})`,
        };
      }

      return undefined;
    });
  }

  private async handleStepComplete(): Promise<{ ok: boolean; prompt?: string; error?: string }> {
    const prev = this.state.step;

    if (prev === 3) {
      const result = await this.handleFinalize();
      if (!result.ok) {
        await this.eventLog?.emitPhaseEnd("failed", result.errors?.join("; "));
        return { ok: false, error: result.errors?.join("; ") };
      }
      this.state.active = false;
      unhookDispatch(this.dispatch, "onCompleteStep");
      await this.eventLog?.emitPhaseEnd("completed");
      this.log("Fix phase complete, plan validation passed");
      return { ok: true, prompt: "Fix phase validation passed. Workflow complete." };
    }

    this.state.step = (prev + 1) as FixStep;
    const nextName = FIX_STEP_NAMES[this.state.step];
    const prompt = formatStep(fixStepGuidance(this.state.step));

    this.log("Fix step complete, advancing", { from: prev, to: this.state.step, name: nextName });
    await this.eventLog?.emitStepTransition(this.state.step, nextName, TOTAL_STEPS);

    return { ok: true, prompt };
  }

  private async handleFinalize(): Promise<{ ok: boolean; errors?: string[] }> {
    return loadAndValidatePlan(this.planDir, this.log);
  }
}
