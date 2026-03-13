// Core types for the koan epic/story orchestrator.
// Shared across driver, phases, tools, and spawn infrastructure.

// No `escalated` status: escalation is asking a question (§11.3.1). The orchestrator
// calls `koan_ask_question` when it needs human input, then decides via retry/skip.
// A separate status created a dead routing path — the driver had nowhere clean to
// send it without duplicating the ask UI flow that IPC already handles.
//
// No `scouting` EpicPhase: scouts are spawned inside the IPC responder during
// intake/decomposer/planner phases, not as a top-level driver phase. Adding
// "scouting" to EpicPhase would imply a driver state that never exists (§12.2.2).
// If a top-level scouting phase is added later, re-add the value then.
//
// StepSequence exists for the orchestrator, which has two distinct step counts
// depending on where in the story lifecycle it runs: pre-execution (2 steps:
// dependency analysis + select) vs post-execution (4 steps: verify + verdict +
// propagate + select next). A single OrchestratorPhase class reads this value
// in begin() to configure its total steps and guidance functions (§9.1).

// Subagent roles — the six LLM roles in the pipeline.
export type SubagentRole = "intake" | "scout" | "decomposer" | "orchestrator" | "planner" | "executor";

// Model tiers — maps to three capability levels.
export type ModelTier = "strong" | "standard" | "cheap";

// Role → model tier mapping. Scouts use cheap models; execution roles use standard.
export const ROLE_MODEL_TIER: Record<SubagentRole, ModelTier> = {
  intake: "strong",
  scout: "cheap",
  decomposer: "strong",
  orchestrator: "strong",
  planner: "strong",
  executor: "standard",
};

// Orchestrator step sequences — configures step count and guidance at spawn time.
export type StepSequence = "pre-execution" | "post-execution";

// Story lifecycle states. Driver manages intermediate transitions; orchestrator tools
// drive the routing transitions via koan_* tool calls.
export type StoryStatus =
  | "pending"    // Initial state: not yet selected
  | "selected"   // Orchestrator selected this story via koan_select_story
  | "planning"   // Driver-internal: planner subagent is running
  | "executing"  // Driver-internal: executor subagent is running
  | "verifying"  // Driver-internal: post-execution orchestrator is running
  | "done"       // Orchestrator verdict: story completed successfully
  | "retry"      // Orchestrator verdict: re-execute with failure context
  | "skipped";   // Orchestrator or driver: story bypassed (budget exhaustion or explicit skip)

// Epic lifecycle phases (driver-managed, not LLM-visible directly).
// Note: "scouting" is intentionally absent — scouts run within other phases via IPC.
export type EpicPhase = "intake" | "decomposition" | "review" | "executing" | "completed";
