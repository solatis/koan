// QR verify phase -- 3-step reviewer subagent that verifies exactly 1 QR item
// against the plan (CONTEXT -> ANALYZE -> CONFIRM). One subagent per item.
// Mirrors PlanDesignPhase lifecycle; no finalize validation -- parent reads
// item status from disk after the reviewer exits.

import { promises as fs } from "node:fs";
import * as path from "node:path";

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import { formatStep } from "../../lib/step.js";
import type { ContextData } from "../../types.js";
import { createLogger, type Logger } from "../../../utils/logger.js";
import { EventLog } from "../../lib/audit.js";
import {
  hookDispatch,
  unhookDispatch,
  type WorkflowDispatch,
  type PlanRef,
} from "../../lib/dispatch.js";
import { checkPermission } from "../../lib/permissions.js";
import type { QRItem, QRFile } from "../../qr/types.js";
import {
  loadQRVerifySystemPrompt,
  buildVerifySystemPrompt,
  buildContextStep,
  buildAnalyzeStep,
  buildConfirmStep,
  type VerifyStep,
} from "./prompts.js";

// -- Constants --

const TOTAL_STEPS = 3;
const STEP_NAMES: Record<VerifyStep, string> = {
  1: "CONTEXT",
  2: "ANALYZE",
  3: "CONFIRM",
};

// -- State --

interface VerifyState {
  active: boolean;
  step: VerifyStep;
  itemId: string;
  step1Prompt: string | null;
  systemPrompt: string | null;
}

// -- Phase --

export class QRVerifyPhase {
  private readonly pi: ExtensionAPI;
  private readonly planDir: string;
  private readonly log: Logger;
  private readonly state: VerifyState;
  private readonly eventLog: EventLog | undefined;
  private readonly dispatch: WorkflowDispatch;
  private readonly planRef: PlanRef;
  private item: QRItem | null = null;

  constructor(
    pi: ExtensionAPI,
    config: { planDir: string; itemId: string },
    dispatch: WorkflowDispatch,
    planRef: PlanRef,
    log?: Logger,
    eventLog?: EventLog,
  ) {
    this.pi = pi;
    this.planDir = config.planDir;
    this.dispatch = dispatch;
    this.planRef = planRef;
    this.log = log ?? createLogger("QRVerify");
    this.eventLog = eventLog;

    this.state = {
      active: false,
      step: 1,
      itemId: config.itemId,
      step1Prompt: null,
      systemPrompt: null,
    };

    this.registerHandlers();
  }

  async begin(): Promise<void> {
    // Verify plan.json exists so koan_get_plan is usable during analysis.
    const planPath = path.join(this.planDir, "plan.json");
    try {
      await fs.access(planPath);
    } catch {
      this.log("plan.json not found", { path: planPath });
      return;
    }

    const contextPath = path.join(this.planDir, "context.json");
    let contextData: ContextData;
    try {
      const raw = await fs.readFile(contextPath, "utf8");
      contextData = JSON.parse(raw) as ContextData;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.log("Failed to read context.json", { error: message });
      return;
    }

    const qrPath = path.join(this.planDir, "qr-plan-design.json");
    let qrFile: QRFile;
    try {
      const raw = await fs.readFile(qrPath, "utf8");
      qrFile = JSON.parse(raw) as QRFile;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.log("Failed to read qr-plan-design.json", { error: message });
      return;
    }

    const item = qrFile.items.find((i) => i.id === this.state.itemId);
    if (!item) {
      this.log("QR item not found", { itemId: this.state.itemId });
      return;
    }
    this.item = item;

    let basePrompt: string;
    try {
      basePrompt = await loadQRVerifySystemPrompt();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.log("Failed to load QR verify system prompt", { error: message });
      return;
    }

    this.state.systemPrompt = buildVerifySystemPrompt(basePrompt);
    this.state.step1Prompt = formatStep(buildContextStep(item, contextData));
    this.state.active = true;
    this.state.step = 1;
    this.planRef.dir = this.planDir;

    hookDispatch(this.dispatch, "onCompleteStep", () => this.handleStepComplete());

    this.log("Starting QR verify workflow", { itemId: this.state.itemId, step: 1 });
    await this.eventLog?.emitPhaseStart(TOTAL_STEPS);
    await this.eventLog?.emitStepTransition(1, STEP_NAMES[1], TOTAL_STEPS);
  }

  private registerHandlers(): void {
    this.pi.on("before_agent_start", () => {
      if (!this.state.active || !this.state.systemPrompt) return undefined;
      return { systemPrompt: this.state.systemPrompt };
    });

    // Step 1 prompt injection. Context event fires before the initial LLM
    // call and replaces the trigger user message with actual step 1 instructions.
    // Handler is a no-op once the step advances past 1.
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

      const perm = checkPermission("qr-plan-design", event.toolName);
      if (!perm.allowed) {
        return { block: true, reason: perm.reason };
      }

      // Step gate: koan_qr_set_item is step-3-only (CONFIRM step).
      // Blocklist so read tools and other approved tools pass through.
      const step = this.state.step;
      if (step < 3 && event.toolName === "koan_qr_set_item") {
        return {
          block: true,
          reason: `koan_qr_set_item available in step 3 (current: ${step})`,
        };
      }

      return undefined;
    });

  }

  private async handleStepComplete(): Promise<{ ok: boolean; prompt?: string; error?: string }> {
    const prev = this.state.step;

    if (prev === 3) {
      this.state.active = false;
      unhookDispatch(this.dispatch, "onCompleteStep");
      await this.eventLog?.emitPhaseEnd("completed");
      this.log("Verification complete");
      return { ok: true, prompt: "Verification complete." };
    }

    this.state.step = (prev + 1) as VerifyStep;
    const stepName = STEP_NAMES[this.state.step];
    const prompt = this.buildStepPrompt(this.state.step);

    this.log("Step complete, advancing", { from: prev, to: this.state.step });
    await this.eventLog?.emitStepTransition(this.state.step, stepName, TOTAL_STEPS);

    return { ok: true, prompt };
  }

  // Item is stored during begin() -- avoids async re-reads for prompt building.
  private buildStepPrompt(step: VerifyStep): string {
    switch (step) {
      case 2:
        return formatStep(buildAnalyzeStep(this.item!));
      case 3:
        return formatStep(buildConfirmStep(this.item!));
      default:
        return "";
    }
  }
}
