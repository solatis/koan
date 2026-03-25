// Tool registration aggregator. Single entry point for koan.ts.
// All tools registered here; RuntimeContext replaces the three separate
// mutable refs (PlanRef, SubagentRef, WorkflowDispatch) from the old design.

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import type { RuntimeContext } from "../lib/runtime-context.js";

import { registerWorkflowTools } from "./workflow.js";
import { registerOrchestratorTools } from "./orchestrator.js";
import { registerAskTools } from "./ask.js";
import { registerReviewArtifactTool } from "./review-artifact.js";
import { registerWorkflowDecisionTools } from "./workflow-decision.js";

export type { RuntimeContext } from "../lib/runtime-context.js";
export { createRuntimeContext } from "../lib/runtime-context.js";

export function registerAllTools(pi: ExtensionAPI, ctx: RuntimeContext): void {
  registerWorkflowTools(pi, ctx);
  registerOrchestratorTools(pi, ctx);
  registerAskTools(pi, ctx);
  registerReviewArtifactTool(pi, ctx);
  registerWorkflowDecisionTools(pi, ctx);
}
