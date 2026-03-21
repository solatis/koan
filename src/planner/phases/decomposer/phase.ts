// Decomposer phase: splits the epic into story sketches.
// Two steps: analysis → decomposition.

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import { createLogger, type Logger } from "../../../utils/logger.js";
import type { RuntimeContext } from "../../lib/runtime-context.js";
import { EventLog } from "../../lib/audit.js";
import { BasePhase } from "../base-phase.js";
import { DECOMPOSER_STEP_NAMES, decomposerSystemPrompt, decomposerStepGuidance } from "./prompts.js";
import type { StepGuidance } from "../../lib/step.js";

export class DecomposerPhase extends BasePhase {
  protected readonly role = "decomposer";
  protected readonly totalSteps = 2;

  constructor(
    pi: ExtensionAPI,
    ctx: RuntimeContext,
    log?: Logger,
    eventLog?: EventLog,
  ) {
    super(pi, ctx, log ?? createLogger("DecomposerPhase"), eventLog);
  }

  protected getSystemPrompt(): string {
    return decomposerSystemPrompt();
  }

  protected getStepName(step: number): string {
    return DECOMPOSER_STEP_NAMES[step] ?? `Step ${step}`;
  }

  protected getStepGuidance(step: number): StepGuidance {
    return decomposerStepGuidance(step);
  }
}
