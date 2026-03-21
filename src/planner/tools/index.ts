// Tool registration aggregator. Single entry point for koan.ts.
// All tools registered here; RuntimeContext replaces the three separate
// mutable refs (PlanRef, SubagentRef, WorkflowDispatch) from the old design.

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import type { RuntimeContext } from "../lib/runtime-context.js";
import type { ConfidenceRef } from "../phases/intake/phase.js";
import type { AuditRef } from "./confidence.js";

import { registerWorkflowTools } from "./workflow.js";
import { registerOrchestratorTools } from "./orchestrator.js";
import { registerAskTools } from "./ask.js";
import { registerConfidenceTool } from "./confidence.js";
import { registerReviewArtifactTool } from "./review-artifact.js";

export type { RuntimeContext } from "../lib/runtime-context.js";
export { createRuntimeContext } from "../lib/runtime-context.js";

export function registerAllTools(pi: ExtensionAPI, ctx: RuntimeContext, confidenceRef: ConfidenceRef, auditRef: AuditRef): void {
  registerWorkflowTools(pi, ctx);
  registerOrchestratorTools(pi, ctx);
  registerAskTools(pi, ctx);
  registerConfidenceTool(pi, confidenceRef, auditRef);
  registerReviewArtifactTool(pi, ctx);
}
