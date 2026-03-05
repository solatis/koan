// QR verify phase -- dynamic-step reviewer subagent that verifies 1..N QR items
// against the plan. Workflow: CONTEXT (once) -> N × (ANALYZE + CONFIRM) -> done.
// Items in a group share a single subagent, amortizing process startup cost.
//
// Dynamic step formula: totalSteps = 1 + (2 * numItems)
//   Step 1:       CONTEXT  (load plan, list all assigned items)
//   Step 2k:      ANALYZE  item k  (k = 1..N)
//   Step 2k+1:    CONFIRM  item k  (record verdict)
//
// Step gating: koan_qr_set_item is blocked until the CONFIRM step for the
// current item (odd-numbered steps >= 3).

import { promises as fs } from "node:fs";
import * as path from "node:path";

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import { formatStep } from "../../lib/step.js";
import { createLogger, type Logger } from "../../../utils/logger.js";
import { EventLog } from "../../lib/audit.js";
import { hookDispatch, unhookDispatch, type WorkflowDispatch, type PlanRef } from "../../lib/dispatch.js";
import { checkPermission } from "../../lib/permissions.js";
import type { QRItem, QRFile } from "../../qr/types.js";
import {
  loadQRVerifySystemPrompt,
  buildVerifySystemPrompt,
  buildContextStep,
  buildAnalyzeStep,
  buildConfirmStep,
} from "./prompts.js";

type WorkPhaseKey = "plan-design" | "plan-code" | "plan-docs";

interface VerifyState {
  active: boolean;
  step: number;
  totalSteps: number;
  itemIds: string[];
  step1Prompt: string | null;
  systemPrompt: string | null;
}

// Map step number to step type and item index.
// Step 1 is CONTEXT. Steps 2..2N+1 alternate ANALYZE/CONFIRM per item.
function stepType(step: number): { kind: "CONTEXT" } | { kind: "ANALYZE"; itemIndex: number } | { kind: "CONFIRM"; itemIndex: number } {
  if (step === 1) return { kind: "CONTEXT" };
  const offset = step - 2; // 0-indexed from step 2
  const itemIndex = Math.floor(offset / 2);
  const isConfirm = offset % 2 === 1;
  return isConfirm ? { kind: "CONFIRM", itemIndex } : { kind: "ANALYZE", itemIndex };
}

function stepName(step: number, numItems: number): string {
  if (step === 1) return "CONTEXT";
  const info = stepType(step);
  if (info.kind === "ANALYZE") return `ANALYZE ${info.itemIndex + 1}/${numItems}`;
  if (info.kind === "CONFIRM") return `CONFIRM ${info.itemIndex + 1}/${numItems}`;
  return `Step ${step}`;
}

export class QRVerifyPhase {
  private readonly pi: ExtensionAPI;
  private readonly planDir: string;
  private readonly workPhase: WorkPhaseKey;
  private readonly qrPhaseKey: `qr-${WorkPhaseKey}`;
  private readonly log: Logger;
  private readonly state: VerifyState;
  private readonly eventLog: EventLog | undefined;
  private readonly dispatch: WorkflowDispatch;
  private readonly planRef: PlanRef;
  private items: QRItem[] = [];

  constructor(
    pi: ExtensionAPI,
    config: { planDir: string; itemIds: string[]; workPhase: WorkPhaseKey },
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
    this.log = log ?? createLogger("QRVerify");
    this.eventLog = eventLog;

    const numItems = config.itemIds.length;
    const totalSteps = 1 + 2 * numItems;

    this.state = {
      active: false,
      step: 1,
      totalSteps,
      itemIds: config.itemIds,
      step1Prompt: null,
      systemPrompt: null,
    };

    this.registerHandlers();
  }

  async begin(): Promise<void> {
    const planPath = path.join(this.planDir, "plan.json");
    try {
      await fs.access(planPath);
    } catch {
      this.log("plan.json not found", { path: planPath });
      return;
    }

    const qrPath = path.join(this.planDir, `qr-${this.workPhase}.json`);
    let qrFile: QRFile;
    try {
      const raw = await fs.readFile(qrPath, "utf8");
      qrFile = JSON.parse(raw) as QRFile;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.log(`Failed to read qr-${this.workPhase}.json`, { error: message });
      return;
    }

    // Resolve all item IDs to QRItem objects.
    const resolvedItems: QRItem[] = [];
    for (const id of this.state.itemIds) {
      const item = qrFile.items.find((i) => i.id === id);
      if (!item) {
        this.log("QR item not found", { itemId: id, phase: this.workPhase });
        return;
      }
      resolvedItems.push(item);
    }
    this.items = resolvedItems;

    let basePrompt: string;
    try {
      basePrompt = await loadQRVerifySystemPrompt();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.log("Failed to load QR verify system prompt", { error: message });
      return;
    }

    this.state.systemPrompt = buildVerifySystemPrompt(basePrompt, this.workPhase, this.items.length);
    const conversationPath = path.join(this.planDir, "conversation.jsonl");
    this.state.step1Prompt = formatStep(buildContextStep(this.items, this.workPhase, conversationPath));
    this.state.active = true;
    this.state.step = 1;
    this.planRef.dir = this.planDir;
    this.planRef.qrPhase = this.workPhase;

    hookDispatch(this.dispatch, "onCompleteStep", () => this.handleStepComplete());

    this.log("Starting QR verify workflow", {
      itemIds: this.state.itemIds,
      itemCount: this.items.length,
      totalSteps: this.state.totalSteps,
      phase: this.workPhase,
      step: 1,
    });
    await this.eventLog?.emitPhaseStart(this.state.totalSteps);
    await this.eventLog?.emitStepTransition(1, "CONTEXT", this.state.totalSteps);
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

      // koan_qr_set_item is only allowed during CONFIRM steps (odd steps >= 3).
      if (event.toolName === "koan_qr_set_item") {
        const info = stepType(this.state.step);
        if (info.kind !== "CONFIRM") {
          return {
            block: true,
            reason: `koan_qr_set_item available only during CONFIRM steps (current: ${stepName(this.state.step, this.items.length)})`,
          };
        }
      }

      return undefined;
    });
  }

  private async handleStepComplete(): Promise<{ ok: boolean; prompt?: string; error?: string }> {
    const prev = this.state.step;

    if (prev >= this.state.totalSteps) {
      this.state.active = false;
      unhookDispatch(this.dispatch, "onCompleteStep");
      await this.eventLog?.emitPhaseEnd("completed");
      this.log("Verification complete", {
        itemCount: this.items.length,
        phase: this.workPhase,
      });
      return { ok: true, prompt: "Verification complete." };
    }

    this.state.step = prev + 1;
    const name = stepName(this.state.step, this.items.length);
    const prompt = this.buildStepPrompt(this.state.step);

    this.log("Step complete, advancing", {
      from: prev,
      to: this.state.step,
      name,
      phase: this.workPhase,
    });
    await this.eventLog?.emitStepTransition(this.state.step, name, this.state.totalSteps);
    return { ok: true, prompt };
  }

  private buildStepPrompt(step: number): string {
    const info = stepType(step);
    if (info.kind === "ANALYZE") {
      return formatStep(buildAnalyzeStep(this.items[info.itemIndex], info.itemIndex, this.items.length));
    }
    if (info.kind === "CONFIRM") {
      return formatStep(buildConfirmStep(this.items[info.itemIndex], info.itemIndex, this.items.length, this.workPhase));
    }
    return "";
  }
}
