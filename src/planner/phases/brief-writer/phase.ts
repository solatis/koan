// Brief-writer phase: reads intake context and produces brief.md.
// Three-step workflow with a review gate:
//
//   Step 1 (Read)          — comprehend context.md; no file writes
//   Step 2 (Draft & Review) — write brief.md, invoke koan_review_artifact;
//                             revise on feedback; advance only after "Accept"
//   Step 3 (Finalize)      — phase complete
//
// Step 2 is the review gate. The LLM loops within step 2 by calling
// koan_review_artifact multiple times before advancing with koan_complete_step.
// validateStepCompletion() enforces that at least one review call occurs before
// the phase can advance past step 2.
//
// Review call tracking: the phase registers an additional tool_call listener
// (after BasePhase's permission listener) to increment a counter each time
// koan_review_artifact is called. The counter persists across the session —
// it does not need to reset because step 2 is entered exactly once in a linear
// workflow; the LLM loops by making multiple review calls before advancing.

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import { createLogger, type Logger } from "../../../utils/logger.js";
import type { RuntimeContext } from "../../lib/runtime-context.js";
import { EventLog } from "../../lib/audit.js";
import { BasePhase } from "../base-phase.js";
import { BRIEF_WRITER_STEP_NAMES, briefWriterSystemPrompt, briefWriterStepGuidance } from "./prompts.js";
import type { StepGuidance } from "../../lib/step.js";

export class BriefWriterPhase extends BasePhase {
  protected readonly role = "brief-writer";
  protected readonly totalSteps = 3;

  // Counts koan_review_artifact calls during this phase session.
  // Used by validateStepCompletion to enforce at least one review before advancing.
  private reviewCallCount = 0;

  constructor(
    pi: ExtensionAPI,
    ctx: RuntimeContext,
    log?: Logger,
    eventLog?: EventLog,
  ) {
    super(pi, ctx, log ?? createLogger("BriefWriterPhase"), eventLog);

    // Track koan_review_artifact invocations so validateStepCompletion can
    // verify that the LLM presented brief.md for review before advancing.
    // Always returns undefined — does not interfere with the base class
    // permission fence registered by BasePhase.registerHandlers().
    pi.on("tool_call", (event) => {
      if (event.toolName === "koan_review_artifact") {
        this.reviewCallCount++;
      }
      return undefined;
    });
  }

  protected getSystemPrompt(): string {
    return briefWriterSystemPrompt();
  }

  protected getStepName(step: number): string {
    return BRIEF_WRITER_STEP_NAMES[step] ?? `Step ${step}`;
  }

  protected getStepGuidance(step: number): StepGuidance {
    return briefWriterStepGuidance(step);
  }

  // Pre-condition: require at least one koan_review_artifact call before
  // advancing from step 2. The LLM must present brief.md for review before
  // completing the Draft & Review step.
  protected async validateStepCompletion(step: number): Promise<string | null> {
    if (step === 2 && this.reviewCallCount === 0) {
      return "You must call koan_review_artifact on brief.md before completing this step. " +
        "Write brief.md, then invoke koan_review_artifact to present it for review.";
    }
    return null;
  }

  // ctx.briefWriterStep is read by the permission fence to block write/edit
  // during the read-only Read step (step 1).
  protected override onStepUpdated(step: number): void {
    this.ctx.briefWriterStep = step;
  }
}
