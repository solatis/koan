// Scout phase: answers one narrow codebase question and writes findings.
// Four-step workflow (orient → investigate → verify → report), cheap model, no user interaction.
// Task context (question, outputFile, role) is received via CLI flags and
// delivered to the LLM through step guidance (returned by koan_complete_step).

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import { createLogger, type Logger } from "../../../utils/logger.js";
import type { RuntimeContext } from "../../lib/runtime-context.js";
import { EventLog } from "../../lib/audit.js";
import { BasePhase } from "../base-phase.js";
import { SCOUT_STEP_NAMES, scoutSystemPrompt, scoutStepGuidance } from "./prompts.js";
import type { StepGuidance } from "../../lib/step.js";

export class ScoutPhase extends BasePhase {
  protected readonly role = "scout";
  protected readonly totalSteps = 4;

  private readonly question: string;
  private readonly outputFile: string;
  private readonly investigatorRole: string;

  constructor(
    pi: ExtensionAPI,
    config: { question: string; outputFile: string; investigatorRole: string },
    ctx: RuntimeContext,
    log?: Logger,
    eventLog?: EventLog,
  ) {
    super(pi, ctx, log ?? createLogger("ScoutPhase"), eventLog);
    this.question = config.question;
    this.outputFile = config.outputFile;
    this.investigatorRole = config.investigatorRole;
  }

  protected getSystemPrompt(): string {
    return scoutSystemPrompt();
  }

  protected getStepName(step: number): string {
    return SCOUT_STEP_NAMES[step] ?? `Step ${step}`;
  }

  protected getStepGuidance(step: number): StepGuidance {
    return scoutStepGuidance(step, this.question, this.outputFile, this.investigatorRole);
  }
}
