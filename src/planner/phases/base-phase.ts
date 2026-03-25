// BasePhase: shared lifecycle for all six koan subagent roles.
// Subclasses define only their step structure and system prompt.
//
// Step-first workflow invariant (see AGENTS.md):
//   Every subagent launches with a minimal boot prompt that contains only
//   "call koan_complete_step". This forces the LLM's very first action to be
//   a tool call rather than text output — critical because pi -p processes exit
//   the moment the LLM finishes a turn without a tool call, with no recovery.
//
//   Step 0 is the silent boot state. The first koan_complete_step call
//   transitions 0→1 and returns step 1 guidance (just-in-time delivery).
//   Subsequent calls advance through steps until the phase completes.
//
// Non-linear step progression:
//   Subclasses may override getNextStep() to implement loops or conditional
//   transitions. getNextStep() MUST be pure — it only returns the next step
//   number. Side effects that accompany a loop decision (state resets, counter
//   increments, event emission) belong in onLoopBack(), which handleStepComplete
//   calls whenever getNextStep() returns a step number less than the current one.
//
//   The default implementation is strictly linear: each step advances to the
//   next, and the final step (totalSteps) signals completion by returning null.
//   IntakePhase overrides both getNextStep() and onLoopBack() to loop steps 2–4
//   until the confidence gate is satisfied.
//
// Lifecycle:
//   constructor → registerHandlers() (hooks event listeners)
//   begin()     → activates phase at step 0, arms onCompleteStep, emits phase_start
//   handleStepComplete(0) → returns step 1 guidance, emits step_transition(1)
//   handleStepComplete(N) → calls getNextStep(N) to determine next step,
//                           calls onLoopBack() on backward transitions,
//                           returns guidance or null when done

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import { createLogger, type Logger } from "../../utils/logger.js";
import { checkPermission } from "../lib/permissions.js";
import { formatStep, type StepGuidance } from "../lib/step.js";
import { EventLog } from "../lib/audit.js";
import type { RuntimeContext } from "../lib/runtime-context.js";

export abstract class BasePhase {
  // Subclasses declare these as readonly properties.
  protected abstract readonly role: string;
  protected abstract readonly totalSteps: number;

  // Subclasses implement these to define step content.
  protected abstract getSystemPrompt(): string;
  protected abstract getStepName(step: number): string;
  protected abstract getStepGuidance(step: number): StepGuidance;

  private step = 0;
  private active = false;

  protected readonly log: Logger;

  constructor(
    protected readonly pi: ExtensionAPI,
    protected readonly ctx: RuntimeContext,
    log?: Logger,
    protected readonly eventLog?: EventLog,
  ) {
    this.log = log ?? createLogger("Phase");
    this.registerHandlers();
  }

  // -- Non-linear progression hook --
  //
  // Returns the step number to transition to after `currentStep` completes,
  // or null to signal phase completion. Subclasses override this to implement
  // confidence loops, conditional branches, or any other non-linear flow.
  //
  // MUST be pure: do not mutate state or emit events here. Side effects that
  // accompany a loop-back (counter increments, state resets, event emission)
  // belong in onLoopBack(), which handleStepComplete calls after this method
  // returns a backward step number.
  //
  // Default: linear progression. The step after totalSteps is null (done).
  protected getNextStep(currentStep: number): number | null {
    if (currentStep === this.totalSteps) return null;
    return currentStep + 1;
  }

  // -- Event handler registration --

  private registerHandlers(): void {
    // Inject the system prompt when this phase is active. The system prompt
    // establishes role identity but deliberately omits task details — those
    // arrive via step 1 guidance so the first message stays minimal.
    this.pi.on("before_agent_start", () => {
      if (!this.active) return undefined;
      return { systemPrompt: this.getSystemPrompt() };
    });

    // Default-deny permission fence: every tool call is checked against the
    // role's allowed set. Prevents roles from using tools outside their scope
    // even though all tools are registered unconditionally at init.
    this.pi.on("tool_call", (event) => {
      if (!this.active) return undefined;
      const perm = checkPermission(
        this.role,
        event.toolName,
        this.ctx.epicDir ?? undefined,
        event.input as Record<string, unknown>,
        this.ctx.currentStep,
      );
      if (!perm.allowed) {
        void this.eventLog?.append({
          kind: "tool_result",
          toolCallId: event.toolCallId,
          tool: event.toolName,
          error: true,
        });
        return { block: true, reason: perm.reason };
      }
      return undefined;
    });

    // NOTE: There is deliberately NO `context` event handler here.
    // A previous design injected step 1 guidance into the first user message,
    // but that front-loaded complex instructions before the LLM had established
    // the koan_complete_step calling pattern — causing weaker models to produce
    // text output and exit without entering the workflow at all.
    // Step guidance is now delivered exclusively through koan_complete_step return values.
  }

  // -- Public lifecycle --

  async begin(): Promise<void> {
    this.active = true;
    this.step = 0; // Boot state: waiting for the first koan_complete_step call.

    if (this.ctx.onCompleteStep !== null) {
      throw new Error(`ctx.onCompleteStep is already occupied — cannot begin ${this.role} phase`);
    }
    this.ctx.onCompleteStep = (thoughts: string) => this.handleStepComplete(thoughts);

    this.log("Starting phase", { role: this.role, step: 0, totalSteps: this.totalSteps });
    await this.eventLog?.emitPhaseStart(this.totalSteps);
    // step_transition is NOT emitted here — it fires when step 1 guidance is first
    // returned, so the event log reflects when the LLM actually begins work.
  }

  // -- Private step progression --

  private async handleStepComplete(thoughts: string): Promise<string | null> {
    void thoughts; // captured in event log via tool_result; escape hatch for models that can't mix text + tool_call

    if (this.step === 0) {
      // Boot transition: the LLM called koan_complete_step as instructed by the
      // boot prompt. Reward it with step 1 guidance. This is the critical moment
      // that establishes the call→receive→work→call pattern for the session.
      this.step = 1;
      this.onStepUpdated(1);
      const prompt = formatStep(this.getStepGuidance(1));
      await this.eventLog?.emitStepTransition(1, this.getStepName(1), this.totalSteps);
      this.log("Boot transition", { role: this.role, to: 1 });
      return prompt;
    }

    // Validate pre-conditions before advancing (subclasses may override).
    const preError = await this.validateStepCompletion(this.step);
    if (preError !== null) {
      // Return the error as the tool result — the LLM sees it and must fix
      // the pre-condition before calling koan_complete_step again.
      return preError;
    }

    const nextStep = this.getNextStep(this.step);

    if (nextStep === null) {
      // Phase complete — return null signals koan_complete_step to reply "Phase complete."
      this.active = false;
      this.ctx.onCompleteStep = null;
      await this.eventLog?.emitPhaseEnd("completed");
      this.log("Phase complete", { role: this.role });
      return null;
    }

    const prev = this.step;
    this.step = nextStep;

    // If the step went backward (loop-back), give the subclass a chance to
    // perform side effects before the new step's guidance is delivered:
    // resetting state, incrementing counters, emitting events. This keeps
    // getNextStep() pure — it only decides where to go, not what to do there.
    if (nextStep < prev) {
      await this.onLoopBack(prev, nextStep);
    }

    this.onStepUpdated(nextStep);
    const prompt = formatStep(this.getStepGuidance(this.step));
    await this.eventLog?.emitStepTransition(this.step, this.getStepName(this.step), this.totalSteps);
    this.log("Step transition", { role: this.role, from: prev, to: this.step });
    return prompt;
  }

  // -- Overridable hooks --

  // Called whenever this.step is updated (including loop-backs). Syncs
  // ctx.currentStep with the current step so the permission fence always
  // reflects the active step. Subclasses may override for additional side effects.
  protected onStepUpdated(step: number): void {
    this.ctx.currentStep = step;
  }

  // Called when a loop-back occurs (nextStep < previousStep), after this.step
  // has been updated but before onStepUpdated() and getStepGuidance() run.
  // Subclasses use this to perform side effects that accompany the loop decision
  // — resetting state, incrementing counters, emitting events — separate from
  // the pure getNextStep() query. The hook is async so event emission can be
  // properly awaited, preserving event order in events.jsonl.
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  protected async onLoopBack(_from: number, _to: number): Promise<void> {
    // Default: no-op.
  }

  // Called before advancing from the given step. Return null to allow
  // advancement, or an error string to block it (returned as the tool
  // result so the LLM sees the message and must fix the pre-condition).
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  protected async validateStepCompletion(_step: number): Promise<string | null> {
    return null; // Default: no pre-conditions.
  }
}
