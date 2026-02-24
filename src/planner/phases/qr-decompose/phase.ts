// QR decompose phase -- 13-step workflow that decomposes a plan into
// verifiable QR items. Mirrors PlanDesignPhase lifecycle exactly.
// Two-tier step gate: koan_qr_add_item unlocks at step 5,
// koan_qr_assign_group unlocks at step 9.

import { promises as fs } from "node:fs";
import * as path from "node:path";

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import {
  loadQRDecomposeSystemPrompt,
  formatContextForDecompose,
  buildDecomposeSystemPrompt,
  decomposeStepGuidance,
  DECOMPOSE_STEP_NAMES,
  type DecomposeStep,
} from "./prompts.js";
import { formatStep } from "../../lib/step.js";
import type { ContextData } from "../../types.js";
import { createLogger, type Logger } from "../../../utils/logger.js";
import { EventLog } from "../../lib/audit.js";
import { hookDispatch, unhookDispatch, type WorkflowDispatch, type PlanRef } from "../../lib/dispatch.js";
import { checkPermission } from "../../lib/permissions.js";
import type { QRFile } from "../../qr/types.js";

// -- Step gate constants --

// Blocklist pattern: only restrict tools this gate owns; everything else
// defers to checkPermission. Avoids blocking read tools or future pi tools.
const QR_ADD_TOOLS = new Set(["koan_qr_add_item"]);
const QR_ASSIGN_TOOLS = new Set(["koan_qr_assign_group"]);
const ADD_ITEM_UNLOCK = 5;
const ASSIGN_GROUP_UNLOCK = 9;
const TOTAL_STEPS = 13;

// -- State --

interface DecomposeState {
  active: boolean;
  step: DecomposeStep;
  step1Prompt: string | null;
  systemPrompt: string | null;
}

// -- Phase --

export class QRDecomposePhase {
  private readonly pi: ExtensionAPI;
  private readonly planDir: string;
  private readonly log: Logger;
  private readonly state: DecomposeState;
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

    let basePrompt: string;
    try {
      basePrompt = await loadQRDecomposeSystemPrompt();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.log("Failed to load qr-decompose system prompt", { error: message });
      return;
    }

    const contextXml = formatContextForDecompose(contextData);
    this.state.systemPrompt = buildDecomposeSystemPrompt(basePrompt);
    this.state.step1Prompt = formatStep(decomposeStepGuidance(1, contextXml));
    this.state.active = true;
    this.state.step = 1;
    this.planRef.dir = this.planDir;

    hookDispatch(this.dispatch, "onCompleteStep", () => this.handleStepComplete());

    this.log("Starting qr-decompose workflow", { step: 1 });
    await this.eventLog?.emitPhaseStart(TOTAL_STEPS);
    await this.eventLog?.emitStepTransition(1, DECOMPOSE_STEP_NAMES[1], TOTAL_STEPS);
  }

  private registerHandlers(): void {
    this.pi.on("before_agent_start", () => {
      if (!this.state.active || !this.state.systemPrompt) return undefined;
      return { systemPrompt: this.state.systemPrompt };
    });

    // Step 1 prompt injection. The CLI message is a process trigger --
    // the context event fires before each LLM call and replaces the
    // user message with the actual step 1 instructions. Handler is a
    // no-op once the step advances past 1.
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

      // Outer boundary: phase permissions (default-deny).
      const perm = checkPermission("qr-plan-design", event.toolName);
      if (!perm.allowed) {
        return { block: true, reason: perm.reason };
      }

      // Inner constraint: two-tier step gate (blocklist, not whitelist).
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
      // Only unhook after successful finalization -- on failure the LLM
      // receives the error as a tool result and may retry within the step.
      this.state.active = false;
      unhookDispatch(this.dispatch, "onCompleteStep");
      await this.eventLog?.emitPhaseEnd("completed");
      this.log("QR decompose finalized, workflow complete");
      return { ok: true, prompt: "QR decomposition complete." };
    }

    this.state.step = (prev + 1) as DecomposeStep;
    const nextName = DECOMPOSE_STEP_NAMES[this.state.step];
    const prompt = formatStep(decomposeStepGuidance(this.state.step));

    this.log("Step complete, advancing", { from: prev, to: this.state.step, name: nextName });
    await this.eventLog?.emitStepTransition(this.state.step, nextName, TOTAL_STEPS);

    return { ok: true, prompt };
  }

  private async handleFinalize(): Promise<{ ok: boolean; errors?: string[] }> {
    const qrPath = path.join(this.planDir, "qr-plan-design.json");
    let qr: QRFile;
    try {
      const raw = await fs.readFile(qrPath, "utf8");
      qr = JSON.parse(raw) as QRFile;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      return { ok: false, errors: [`Failed to read qr-plan-design.json: ${message}`] };
    }

    const errors: string[] = [];
    if (!qr.items || qr.items.length === 0) {
      errors.push("No QR items generated");
    } else {
      const ungrouped = qr.items.filter((i) => i.group_id === null);
      if (ungrouped.length > 0) {
        const ids = ungrouped.map((i) => i.id).join(", ");
        errors.push(`Ungrouped items: ${ids}`);
      }
    }

    if (errors.length > 0) {
      this.log("QR decompose validation failed", { errors });
      return { ok: false, errors };
    }

    this.log("QR decompose validation passed");
    return { ok: true };
  }
}
