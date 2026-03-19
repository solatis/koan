// Intake phase: reads conversation, scouts codebase, asks clarifying questions,
// and writes context.md — the sole input for all downstream phases.
//
// Five-step workflow with a confidence-gated loop:
//
//   Step 1 (Extract)    — read-only comprehension of conversation.jsonl
//   Step 2 (Scout)      — dispatch codebase scouts for targeted exploration
//   Step 3 (Deliberate) — enumerate knowns/unknowns, ask user questions
//   Step 4 (Reflect)    — self-verify completeness, set confidence level
//   Step 5 (Synthesize) — write context.md from all accumulated findings
//
// Steps 2–4 form the confidence loop. After Reflect, getNextStep() checks
// ctx.intakeConfidence:
//   - If "certain" or max iterations reached → return 5 (Synthesize)
//   - Otherwise → return 2 (Scout), triggering a loop-back
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
// Step 1 is read-only: the permission fence blocks koan_request_scouts,
// koan_ask_question, koan_set_confidence, write, and edit during that step,
// enforced via ctx.intakeStep which is kept in sync via onStepUpdated().

import * as path from "node:path";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import { createLogger, type Logger } from "../../../utils/logger.js";
import type { RuntimeContext } from "../../lib/runtime-context.js";
import { EventLog } from "../../lib/audit.js";
import { BasePhase } from "../base-phase.js";
import { INTAKE_STEP_NAMES, intakeSystemPrompt, intakeStepGuidance } from "./prompts.js";
import type { StepGuidance } from "../../lib/step.js";

export class IntakePhase extends BasePhase {
  protected readonly role = "intake";
  protected readonly totalSteps = 5;

  // Maximum number of Scout→Deliberate→Reflect iterations before forcing exit
  // to Synthesize regardless of confidence level.
  private static readonly MAX_ITERATIONS = 4;

  // Current loop iteration (1-based). Starts at 1 for the initial pass through
  // steps 2–4; incremented in onLoopBack() each time the loop continues.
  private iteration = 1;

  private readonly conversationPath: string;

  constructor(
    pi: ExtensionAPI,
    config: { epicDir: string },
    ctx: RuntimeContext,
    log?: Logger,
    eventLog?: EventLog,
  ) {
    super(pi, ctx, log ?? createLogger("IntakePhase"), eventLog);
    this.conversationPath = path.join(config.epicDir, "conversation.jsonl");
  }

  protected getSystemPrompt(): string {
    return intakeSystemPrompt();
  }

  protected getStepName(step: number): string {
    const base = INTAKE_STEP_NAMES[step] ?? `Step ${step}`;
    // Annotate loop steps with the iteration number so the UI shows
    // e.g. "Scout (round 2)" instead of just "Scout".
    if (step >= 2 && step <= 4 && this.iteration > 1) {
      return `${base} (round ${this.iteration})`;
    }
    return base;
  }

  protected getStepGuidance(step: number): StepGuidance {
    return intakeStepGuidance(step, this.conversationPath, this.iteration);
  }

  // -- Non-linear progression: pure query, no side effects --
  //
  // Step 4 (Reflect) is the loop gate. Returns 2 (Scout) to loop back, or 5
  // (Synthesize) to exit. Side effects for the loop-back case (iteration
  // increment, confidence reset, event emission) live in onLoopBack().
  protected getNextStep(currentStep: number): number | null {
    if (currentStep === 4) {
      const confidence = this.ctx.intakeConfidence;
      const isExhausted = this.iteration >= IntakePhase.MAX_ITERATIONS;

      if (confidence === "certain" || isExhausted) {
        if (isExhausted && confidence !== "certain") {
          this.log("Max iterations reached — forcing exit to Synthesize", {
            iteration: this.iteration,
            confidence,
          });
        }
        return 5;
      }

      // Signal loop-back. onLoopBack() handles the side effects.
      return 2;
    }

    // Step 5 (Synthesize) is the final step.
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
    this.iteration++;
    this.ctx.intakeConfidence = null;
    this.ctx.intakeIteration = this.iteration;
    await this.eventLog?.emitIterationStart(this.iteration, IntakePhase.MAX_ITERATIONS);
    this.log("Confidence loop: iterating", { newIteration: this.iteration });
  }

  // -- Pre-condition enforcement for Reflect (step 4) --
  //
  // The LLM must call koan_set_confidence before koan_complete_step during
  // the Reflect step. If it hasn't, we return an error message that the LLM
  // sees as the tool result — it must fix the pre-condition before retrying.
  protected async validateStepCompletion(step: number): Promise<string | null> {
    if (step === 4 && this.ctx.intakeConfidence === null) {
      return "You must call koan_set_confidence before completing the Reflect step. " +
        "Assess your confidence level based on the verification questions you answered, " +
        "then call koan_set_confidence, then call koan_complete_step.";
    }
    return null;
  }

  // -- Sync ctx fields whenever the active step changes --
  //
  // ctx.intakeStep is read by the permission fence to block side-effecting tools
  // during the read-only Extract step (step 1).
  //
  // iteration_start is emitted here for iteration 1 when Scout (step 2) is first
  // entered. Subsequent iterations emit iteration_start via onLoopBack(). This
  // ensures the web UI always knows which iteration is active from the moment
  // scouting begins, not just after the first confidence assessment.
  //
  // The void on emitIterationStart is intentional: onStepUpdated is synchronous.
  // EventLog.append() serializes all appends via an internal promise queue, so
  // this event is enqueued before the emitStepTransition that follows in
  // handleStepComplete, preserving correct order in events.jsonl.
  protected override onStepUpdated(step: number): void {
    this.ctx.intakeStep = step;
    this.ctx.intakeIteration = this.iteration;

    if (step === 2 && this.iteration === 1) {
      void this.eventLog?.emitIterationStart(1, IntakePhase.MAX_ITERATIONS);
    }
  }
}
