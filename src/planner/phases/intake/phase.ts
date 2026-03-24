// Intake phase: reads conversation, scouts codebase, asks clarifying questions,
// and writes landscape.md — the sole input for all downstream phases.
//
// Five-step workflow with a confidence-gated loop:
//
//   Step 1 (Extract)    — read-only comprehension of conversation.jsonl
//   Step 2 (Scout)      — dispatch codebase scouts for targeted exploration
//   Step 3 (Deliberate) — enumerate knowns/unknowns, ask user questions
//   Step 4 (Reflect)    — self-verify completeness, set confidence level
//   Step 5 (Synthesize & Review) — write landscape.md from all accumulated findings
//
// Steps 2-4 form the confidence loop. After Reflect, getNextStep() checks
// intakeState.confidence:
//   - If "certain" or max iterations reached -> return 5 (Synthesize & Review)
//   - Otherwise -> return 2 (Scout), triggering a loop-back
//
// getNextStep() is pure — it only returns the next step number. All side effects
// that accompany a loop-back (confidence reset, iteration increment, event emission)
// live in onLoopBack(), which BasePhase calls after detecting a backward transition.
// This keeps the two concerns separate and makes getNextStep() safe to reason about.
//
// The loop enforces that koan_set_confidence is called before koan_complete_step
// in Reflect via validateStepCompletion(). Confidence is reset to null in onLoopBack()
// so each iteration requires a fresh assessment.
//
// Step 5 enforces that koan_review_artifact is called before koan_complete_step
// via validateStepCompletion(). This ensures landscape.md is presented for user
// review before the phase advances.
//
// Step 1 is read-only: the permission fence blocks koan_request_scouts,
// koan_ask_question, koan_set_confidence, write, and edit during that step,
// enforced via ctx.currentStep which BasePhase.onStepUpdated() keeps in sync.

import * as path from "node:path";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import { createLogger, type Logger } from "../../../utils/logger.js";
import type { RuntimeContext } from "../../lib/runtime-context.js";
import { EventLog } from "../../lib/audit.js";
import { BasePhase } from "../base-phase.js";
import { INTAKE_STEP_NAMES, intakeSystemPrompt, intakeStepGuidance } from "./prompts.js";
import type { StepGuidance } from "../../lib/step.js";
import type { ConfidenceLevel } from "../../tools/confidence.js";

// -- Intake-private state --

interface IntakeState {
  confidence: ConfidenceLevel | null;
  iteration: number;
}

// ConfidenceRef is a stable object created at IntakePhase construction time.
// Tool registration happens at pi init before before_agent_start, so the tool
// cannot receive runtime state directly -- it receives this stable mutable-ref
// instead.
export interface ConfidenceRef {
  get iteration(): number;
  setConfidence(level: ConfidenceLevel): void;
}

export class IntakePhase extends BasePhase {
  protected readonly role = "intake";
  protected readonly totalSteps = 5;

  // Maximum number of Scout->Deliberate->Reflect iterations before forcing exit
  // to Synthesize regardless of confidence level.
  private static readonly MAX_ITERATIONS = 4;

  private readonly intakeState: IntakeState = { confidence: null, iteration: 1 };

  public readonly confidenceRef: ConfidenceRef;

  private readonly conversationPath: string;

  // Tracks whether the last koan_review_artifact call was accepted by the user.
  // null = never reviewed; true = last review accepted; false = last review had feedback.
  // validateStepCompletion gates on this for step 5. See REVIEW_PROTOCOL.
  private lastReviewAccepted: boolean | null = null;

  constructor(
    pi: ExtensionAPI,
    ctx: RuntimeContext,
    log?: Logger,
    eventLog?: EventLog,
  ) {
    super(pi, ctx, log ?? createLogger("IntakePhase"), eventLog);
    this.conversationPath = path.join(ctx.epicDir!, "conversation.jsonl");

    const state = this.intakeState;
    this.confidenceRef = {
      get iteration() { return state.iteration; },
      setConfidence(level: ConfidenceLevel) { state.confidence = level; },
    };

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
    return intakeSystemPrompt();
  }

  protected getStepName(step: number): string {
    const base = INTAKE_STEP_NAMES[step] ?? `Step ${step}`;
    // Annotate loop steps with the iteration number so the UI shows
    // e.g. "Scout (round 2)" instead of just "Scout".
    if (step >= 2 && step <= 4 && this.intakeState.iteration > 1) {
      return `${base} (round ${this.intakeState.iteration})`;
    }
    return base;
  }

  protected getStepGuidance(step: number): StepGuidance {
    return intakeStepGuidance(step, this.conversationPath, this.intakeState.iteration, this.ctx.epicDir!);
  }

  // -- Non-linear progression: pure query, no side effects --
  //
  // Step 4 (Reflect) is the loop gate. Returns 2 (Scout) to loop back, or 5
  // (Synthesize & Review) to exit. Side effects for the loop-back case
  // (iteration increment, confidence reset, event emission) live in onLoopBack().
  protected getNextStep(currentStep: number): number | null {
    if (currentStep === 4) {
      const confidence = this.intakeState.confidence;
      const isExhausted = this.intakeState.iteration >= IntakePhase.MAX_ITERATIONS;

      if (confidence === "certain" || isExhausted) {
        if (isExhausted && confidence !== "certain") {
          this.log("Max iterations reached -- forcing exit to Synthesize", {
            iteration: this.intakeState.iteration,
            confidence,
          });
        }
        return 5;
      }

      // Signal loop-back. onLoopBack() handles the side effects.
      return 2;
    }

    // Step 5 (Synthesize & Review) is the final step.
    if (currentStep === 5) return null;

    // All other steps: linear progression.
    return currentStep + 1;
  }

  // -- Loop-back side effects --
  //
  // Called by BasePhase after getNextStep() returns a backward step number.
  // Increments the iteration counter, resets confidence so the next Reflect
  // step requires a fresh assessment, and emits the iteration_start event.
  // Properly awaited so the event appears in correct sequence in events.jsonl.
  protected override async onLoopBack(_from: number, _to: number): Promise<void> {
    this.intakeState.iteration++;
    this.intakeState.confidence = null;
    await this.eventLog?.emitIterationStart(this.intakeState.iteration, IntakePhase.MAX_ITERATIONS);
    this.log("Confidence loop: iterating", { newIteration: this.intakeState.iteration });
  }

  // -- Pre-condition enforcement for Reflect (step 4) and Synthesize & Review (step 5) --
  //
  // Step 4: The LLM must call koan_set_confidence before koan_complete_step.
  // Step 5: The LLM must call koan_review_artifact before koan_complete_step.
  // If a pre-condition is unmet, we return an error message that the LLM
  // sees as the tool result — it must fix the pre-condition before retrying.
  protected async validateStepCompletion(step: number): Promise<string | null> {
    if (step === 4 && this.intakeState.confidence === null) {
      return "You must call koan_set_confidence before completing the Reflect step. " +
        "Assess your confidence level based on the verification questions you answered, " +
        "then call koan_set_confidence, then call koan_complete_step.";
    }
    if (step === 5) {
      if (this.lastReviewAccepted === null) {
        return "You must call koan_review_artifact on landscape.md before completing this step. " +
          "Write landscape.md, then invoke koan_review_artifact to present it for review.";
      }
      if (!this.lastReviewAccepted) {
        return "The user provided feedback on your artifact — you must address it. " +
          "Revise landscape.md based on the feedback, then call koan_review_artifact again. " +
          "You cannot complete this step until the user accepts.";
      }
    }
    return null;
  }

  // -- Intake-specific side effects on step changes --
  //
  // BasePhase.onStepUpdated() handles writing ctx.currentStep. This override
  // exists only for two intake-specific side effects:
  //   1. Reset lastReviewAccepted when entering step 5 so only step-5 reviews
  //      count toward the validateStepCompletion gate.
  //   2. Emit iteration_start for iteration 1 when Scout (step 2) is first
  //      entered. Subsequent iterations emit iteration_start via onLoopBack().
  //
  // The void on emitIterationStart is intentional: onStepUpdated is synchronous.
  // EventLog.append() serializes all appends via an internal promise queue, so
  // this event is enqueued before the emitStepTransition that follows in
  // handleStepComplete, preserving correct order in events.jsonl.
  protected override onStepUpdated(step: number): void {
    super.onStepUpdated(step);

    // Reset lastReviewAccepted when entering step 5 so only step-5 reviews
    // count toward the validateStepCompletion gate. Without this, a spurious
    // koan_review_artifact call during the confidence loop (steps 2–4) would
    // satisfy the gate before the LLM has written landscape.md.
    if (step === 5) {
      this.lastReviewAccepted = null;
    }

    if (step === 2 && this.intakeState.iteration === 1) {
      void this.eventLog?.emitIterationStart(1, IntakePhase.MAX_ITERATIONS);
    }
  }
}
