// QR decompose phase -- 13-step workflow that decomposes a plan phase into
// verifiable QR items. Two-tier step gate: koan_qr_add_item unlocks at step 5,
// koan_qr_assign_group unlocks at step 9.

import { promises as fs } from "node:fs";
import * as path from "node:path";

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import {
  loadQRDecomposeSystemPrompt,
  buildDecomposeSystemPrompt,
  decomposeStepGuidance,
  DECOMPOSE_STEP_NAMES,
  type DecomposeStep,
  type WorkPhaseKey,
} from "./prompts.js";
import { formatStep } from "../../lib/step.js";
import { createLogger, type Logger } from "../../../utils/logger.js";
import { EventLog } from "../../lib/audit.js";
import { hookDispatch, unhookDispatch, type WorkflowDispatch, type PlanRef } from "../../lib/dispatch.js";
import { checkPermission } from "../../lib/permissions.js";
import type { QRFile } from "../../qr/types.js";

const QR_ADD_TOOLS = new Set(["koan_qr_add_item"]);
const QR_ASSIGN_TOOLS = new Set(["koan_qr_assign_group"]);
const ADD_ITEM_UNLOCK = 5;
const ASSIGN_GROUP_UNLOCK = 9;
const TOTAL_STEPS = 13;

interface DecomposeState {
  active: boolean;
  step: DecomposeStep;
  step1Prompt: string | null;
  systemPrompt: string | null;
}

export class QRDecomposePhase {
  private readonly pi: ExtensionAPI;
  private readonly planDir: string;
  private readonly workPhase: WorkPhaseKey;
  private readonly qrPhaseKey: `qr-${WorkPhaseKey}`;
  private readonly log: Logger;
  private readonly state: DecomposeState;
  private readonly eventLog: EventLog | undefined;
  private readonly dispatch: WorkflowDispatch;
  private readonly planRef: PlanRef;

  constructor(
    pi: ExtensionAPI,
    config: { planDir: string; workPhase: WorkPhaseKey },
    dispatch: WorkflowDispatch,
    planRef: PlanRef,
    log?: Logger,
    eventLog?: EventLog,
  ) {
    this.pi = pi;
    this.planDir = config.planDir;
    this.workPhase = config.workPhase;
    this.qrPhaseKey = `qr-${config.workPhase}`;
    this.dispatch = dispatch;
    this.planRef = planRef;
    this.log = log ?? createLogger("QRDecompose");
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
      basePrompt = await loadQRDecomposeSystemPrompt();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.log("Failed to load qr-decompose system prompt", { error: message });
      return;
    }

    this.state.systemPrompt = buildDecomposeSystemPrompt(basePrompt, this.workPhase);
    const conversationPath = path.join(this.planDir, "conversation.jsonl");
    this.state.step1Prompt = formatStep(decomposeStepGuidance(1, this.workPhase, conversationPath));
    this.state.active = true;
    this.state.step = 1;
    this.planRef.dir = this.planDir;
    this.planRef.qrPhase = this.workPhase;

    hookDispatch(this.dispatch, "onCompleteStep", () => this.handleStepComplete());

    this.log("Starting qr-decompose workflow", { step: 1, phase: this.workPhase });
    await this.eventLog?.emitPhaseStart(TOTAL_STEPS);
    await this.eventLog?.emitStepTransition(1, DECOMPOSE_STEP_NAMES[1], TOTAL_STEPS);
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

      const perm = checkPermission(this.qrPhaseKey, event.toolName);
      if (!perm.allowed) return { block: true, reason: perm.reason };

      const step = this.state.step;
      if (step < ADD_ITEM_UNLOCK && QR_ADD_TOOLS.has(event.toolName)) {
        return {
          block: true,
          reason: `${event.toolName} available from step ${ADD_ITEM_UNLOCK} (current: ${step})`,
        };
      }
      if (step < ASSIGN_GROUP_UNLOCK && QR_ASSIGN_TOOLS.has(event.toolName)) {
        return {
          block: true,
          reason: `${event.toolName} available from step ${ASSIGN_GROUP_UNLOCK} (current: ${step})`,
        };
      }

      return undefined;
    });
  }

  private async handleStepComplete(): Promise<{ ok: boolean; prompt?: string; error?: string }> {
    const prev = this.state.step;

    if (prev === 13) {
      const result = await this.handleFinalize();
      if (!result.ok) {
        await this.eventLog?.emitPhaseEnd("failed", result.errors?.join("; "));
        return { ok: false, error: result.errors?.join("; ") };
      }

      this.state.active = false;
      unhookDispatch(this.dispatch, "onCompleteStep");
      await this.eventLog?.emitPhaseEnd("completed");
      this.log("QR decompose finalized, workflow complete", { phase: this.workPhase });
      return { ok: true, prompt: "QR decomposition complete." };
    }

    this.state.step = (prev + 1) as DecomposeStep;
    const nextName = DECOMPOSE_STEP_NAMES[this.state.step];
    const prompt = formatStep(decomposeStepGuidance(this.state.step, this.workPhase));

    this.log("Step complete, advancing", { from: prev, to: this.state.step, name: nextName, phase: this.workPhase });
    await this.eventLog?.emitStepTransition(this.state.step, nextName, TOTAL_STEPS);
    return { ok: true, prompt };
  }

  private async handleFinalize(): Promise<{ ok: boolean; errors?: string[] }> {
    const qrPath = path.join(this.planDir, `qr-${this.workPhase}.json`);
    let qr: QRFile;
    try {
      const raw = await fs.readFile(qrPath, "utf8");
      qr = JSON.parse(raw) as QRFile;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      return { ok: false, errors: [`Failed to read qr-${this.workPhase}.json: ${message}`] };
    }

    const errors: string[] = [];
    if (!qr.items || qr.items.length === 0) {
      errors.push("No QR items generated");
    } else {
      const ungrouped = qr.items.filter((i) => i.group_id === null);
      if (ungrouped.length > 0) {
        errors.push(`Ungrouped items: ${ungrouped.map((i) => i.id).join(", ")}`);
      }
    }

    if (errors.length > 0) {
      this.log("QR decompose validation failed", { errors, phase: this.workPhase });
      return { ok: false, errors };
    }

    this.log("QR decompose validation passed", { phase: this.workPhase });
    return { ok: true };
  }
}
