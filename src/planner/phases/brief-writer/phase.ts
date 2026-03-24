// Brief-writer phase: reads intake context and produces brief.md.
// Three-step workflow with a review gate:
//
//   Step 1 (Read)          — comprehend landscape.md; no file writes
//   Step 2 (Draft & Review) — write brief.md, invoke koan_review_artifact;
//                             revise on feedback; advance only after acceptance
//   Step 3 (Finalize)      — phase complete
//
// Step 2 is the review gate. The LLM loops within step 2 by calling
// koan_review_artifact until the user accepts. validateStepCompletion()
// enforces this mechanically — koan_complete_step is rejected unless
// the last review response was ACCEPTED.
//
// Review outcome tracking: a tool_call listener marks lastReviewAccepted=false
// when koan_review_artifact is called; a tool_result listener checks the
// response text for the "ACCEPTED" prefix and sets lastReviewAccepted=true.
// This two-phase tracking means the gate cannot be fooled by calling
// koan_complete_step before the review response arrives.

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

  // Tracks whether the last koan_review_artifact call was accepted by the user.
  // null = never reviewed; true = last review accepted; false = last review had feedback.
  // validateStepCompletion gates on this: koan_complete_step is rejected unless
  // the last review was accepted. This mechanically enforces the review loop
  // described in the REVIEW_PROTOCOL system prompt.
  private lastReviewAccepted: boolean | null = null;

  constructor(
    pi: ExtensionAPI,
    ctx: RuntimeContext,
    log?: Logger,
    eventLog?: EventLog,
  ) {
    super(pi, ctx, log ?? createLogger("BriefWriterPhase"), eventLog);

    // When koan_review_artifact is called, mark as pending (not yet accepted).
    pi.on("tool_call", (event) => {
      if (event.toolName === "koan_review_artifact") {
        this.lastReviewAccepted = false;
      }
      return undefined;
    });

    // When koan_review_artifact returns, check the response for ACCEPTED.
    pi.on("tool_result", (event) => {
      if (event.toolName === "koan_review_artifact" && !event.isError) {
        const text = event.content?.[0];
        if (text && "text" in text && typeof text.text === "string") {
          this.lastReviewAccepted = text.text.startsWith("ACCEPTED");
        }
      }
    });
  }

  protected getSystemPrompt(): string {
    return briefWriterSystemPrompt();
  }

  protected getStepName(step: number): string {
    return BRIEF_WRITER_STEP_NAMES[step] ?? `Step ${step}`;
  }

  protected getStepGuidance(step: number): StepGuidance {
    return briefWriterStepGuidance(step, this.ctx.epicDir!);
  }

  // Pre-condition: the last koan_review_artifact call must have been accepted.
  // This mechanically enforces the review loop — the LLM cannot skip past
  // user feedback by calling koan_complete_step.
  protected async validateStepCompletion(step: number): Promise<string | null> {
    if (step === 2) {
      if (this.lastReviewAccepted === null) {
        return "You must call koan_review_artifact on brief.md before completing this step. " +
          "Write brief.md, then invoke koan_review_artifact to present it for review.";
      }
      if (!this.lastReviewAccepted) {
        return "The user provided feedback on your artifact — you must address it. " +
          "Revise brief.md based on the feedback, then call koan_review_artifact again. " +
          "You cannot complete this step until the user accepts.";
      }
    }
    return null;
  }
}
