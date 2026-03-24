// Default-deny role-based permissions for koan subagents.
//
// Permission model overview:
//   1. READ_TOOLS (bash, read, grep, glob, find, ls) are always allowed for all
//      roles. This is an accepted limitation (§11.9, §12.5): distinguishing
//      "read bash" from "write bash" is intractable at the permission layer.
//      Prompt engineering constrains intended bash use; enforcement does not.
//      Do not assume bash is restricted to roles that list it explicitly.
//
//   2. ROLE_PERMISSIONS controls koan-specific tools and write/edit access.
//      Unknown roles are blocked under default-deny policy.
//
//   3. Planning roles (intake, scout, decomposer, brief-writer, orchestrator,
//      planner) have write/edit access path-scoped to the epic directory. Only
//      the executor role has unrestricted write access — it must modify the
//      codebase.

import * as path from "node:path";

import { createLogger } from "../../utils/logger.js";

const log = createLogger("permissions");

// Read tools always allowed for all roles — early return in checkPermission.
const READ_TOOLS = new Set(["read", "bash", "grep", "glob", "find", "ls"]);
const WRITE_TOOLS = new Set(["edit", "write"]);

// Tools allowed per role beyond READ_TOOLS.
// Write/edit are tracked here but enforced via path-scoping below.
export const ROLE_PERMISSIONS: ReadonlyMap<string, ReadonlySet<string>> = new Map([
  [
    "intake",
    new Set([
      "koan_complete_step",
      "koan_ask_question",
      "koan_request_scouts",
      "koan_set_confidence",
      "koan_review_artifact",
      "edit",
      "write",
    ]),
  ],
  [
    "scout",
    new Set([
      "koan_complete_step",
      "edit",
      "write",
      // No koan_ask_question — scouts are narrow investigators; no user interaction.
      // No koan_request_scouts — scouts do not spawn scouts.
    ]),
  ],
  [
    "decomposer",
    new Set([
      "koan_complete_step",
      "koan_ask_question",
      "koan_request_scouts",
      "edit",
      "write",
    ]),
  ],
  [
    "brief-writer",
    new Set([
      "koan_complete_step",
      "koan_review_artifact",
      "edit",
      "write",
      // No koan_ask_question — the brief-writer uses artifact review, not structured questions.
      // No koan_request_scouts — all codebase context arrives via landscape.md from intake.
    ]),
  ],
  [
    "orchestrator",
    new Set([
      "koan_complete_step",
      "koan_ask_question",
      // koan_request_scouts excluded from orchestrator — scouts serve planning roles;
      // orchestrator uses bash for verification.
      "koan_select_story",
      "koan_complete_story",
      "koan_retry_story",
      "koan_skip_story",
      "edit",
      "write",
      "bash", // also in READ_TOOLS; explicit here for documentation
    ]),
  ],
  [
    "planner",
    new Set([
      "koan_complete_step",
      "koan_ask_question",
      "koan_request_scouts",
      "edit",
      "write",
    ]),
  ],
  [
    "executor",
    new Set([
      "koan_complete_step",
      "koan_ask_question",
      "edit",
      "write",
      "bash", // also in READ_TOOLS; explicit here for documentation
    ]),
  ],
]);

// Planning roles write only inside the epic directory.
// Executor has unrestricted write access (must implement stories in the codebase).
const PLANNING_ROLES = new Set(["intake", "scout", "decomposer", "brief-writer", "orchestrator", "planner"]);

// STEP_1_BLOCKED_TOOLS: tools disallowed during the intake Extract step (step 1)
// and brief-writer Read step (step 1). Step 1 is read-only comprehension.
// Blocking these tools here provides a mechanical enforcement layer on top of
// the prompt-level prohibition.
const STEP_1_BLOCKED_TOOLS = new Set([
  "koan_request_scouts",
  "koan_ask_question",
  "koan_set_confidence",
  "write",
  "edit",
]);

// STEP_3_BLOCKED_TOOLS: tools disallowed during the intake Deliberate step (step 3).
// Confidence assessment belongs exclusively in the Reflect step (step 4).
// Allowing koan_set_confidence during Deliberate lets the LLM pre-commit to a
// confidence level before verification, anchoring the subsequent Reflect step
// toward premature "certain" declarations.
const STEP_3_BLOCKED_TOOLS = new Set([
  "koan_set_confidence",
]);

export function checkPermission(
  role: string,
  toolName: string,
  epicDir?: string,
  toolArgs?: Record<string, unknown>,
  currentStep?: number,
): { allowed: boolean; reason?: string } {
  // Read tools are always allowed — check before role map lookup.
  if (READ_TOOLS.has(toolName)) {
    return { allowed: true };
  }

  // Intake step 1 (Extract) is read-only: block all side-effecting tools so
  // the LLM cannot frontload scouting or question-asking before it has read
  // and understood the conversation.
  if (role === "intake" && currentStep === 1 && STEP_1_BLOCKED_TOOLS.has(toolName)) {
    return {
      allowed: false,
      reason: `${toolName} is not available during the Extract step (step 1). ` +
        "Complete koan_complete_step first to advance to the Scout step.",
    };
  }

  // Intake step 3 (Deliberate): block koan_set_confidence so the LLM cannot
  // pre-commit to a confidence level before the Reflect step's verification.
  if (role === "intake" && currentStep === 3 && STEP_3_BLOCKED_TOOLS.has(toolName)) {
    return {
      allowed: false,
      reason: `${toolName} is not available during the Deliberate step (step 3). ` +
        "Confidence assessment belongs in the Reflect step (step 4).",
    };
  }

  // Brief-writer step 1 (Read) is read-only: block write and edit so the LLM
  // cannot draft files before it has comprehended landscape.md.
  if (role === "brief-writer" && currentStep === 1 && STEP_1_BLOCKED_TOOLS.has(toolName)) {
    return {
      allowed: false,
      reason: `${toolName} is not available during the Read step (step 1). ` +
        "Complete koan_complete_step first to advance to the Draft & Review step.",
    };
  }

  // Unknown role: blocked under default-deny policy.
  if (!ROLE_PERMISSIONS.has(role)) {
    log("Unknown role blocked", { role, toolName });
    return { allowed: false, reason: `Unknown role: ${role}` };
  }

  const roleAllowed = ROLE_PERMISSIONS.get(role)!;

  if (!roleAllowed.has(toolName)) {
    return { allowed: false, reason: `${toolName} is not available for role ${role}` };
  }

  // Path-scope enforcement: planning roles may only write inside the epic directory.
  if (WRITE_TOOLS.has(toolName) && PLANNING_ROLES.has(role)) {
    if (epicDir && toolArgs) {
      const rawPath = toolArgs["path"];
      if (typeof rawPath === "string") {
        const resolvedTool = path.resolve(rawPath);
        const resolvedEpic = path.resolve(epicDir);
        if (!resolvedTool.startsWith(resolvedEpic + path.sep) && resolvedTool !== resolvedEpic) {
          log("Write blocked: path outside epic dir", { role, toolName, rawPath, epicDir });
          return {
            allowed: false,
            reason: `${toolName} path "${rawPath}" is outside epic directory`,
          };
        }
      }
    }
    // No epicDir or no path arg: allow (cannot scope-check without context).
    return { allowed: true };
  }

  return { allowed: true };
}
