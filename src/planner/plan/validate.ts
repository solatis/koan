import { promises as fs } from "node:fs";
import * as path from "node:path";

import type { Logger } from "../../utils/logger.js";
import type { Plan } from "./types.js";

export interface ValidationResult {
  ok: boolean;
  errors: string[];
}

export function validatePlanDesign(p: Plan): ValidationResult {
  const errors: string[] = [];

  if (p.overview.problem.trim().length === 0) {
    errors.push("overview.problem must not be empty");
  }

  if (p.milestones.length === 0) {
    errors.push("plan must have at least one milestone");
  }

  for (const m of p.milestones) {
    if (m.code_intents.length === 0) {
      errors.push(`milestone ${m.id} must have at least one code_intent`);
    }
  }

  return { ok: errors.length === 0, errors };
}

export function validateRefs(p: Plan): ValidationResult {
  const errors: string[] = [];
  const decisionIds = new Set(p.planning_context.decision_log.map((d) => d.id));
  const milestoneIds = new Set(p.milestones.map((m) => m.id));

  for (const m of p.milestones) {
    const intentIds = new Set(m.code_intents.map((ci) => ci.id));

    for (const ci of m.code_intents) {
      for (const ref of ci.decision_refs) {
        if (!decisionIds.has(ref)) {
          errors.push(`${ci.id}.decision_refs '${ref}' not in decisions`);
        }
      }
    }

    for (const cc of m.code_changes) {
      if (cc.intent_ref && !intentIds.has(cc.intent_ref)) {
        errors.push(
          `${cc.id}.intent_ref '${cc.intent_ref}' not in milestone ${m.id} intents`,
        );
      }
    }
  }

  for (const ra of p.planning_context.rejected_alternatives) {
    if (!decisionIds.has(ra.decision_ref)) {
      errors.push(
        `rejected_alternative ${ra.id}.decision_ref '${ra.decision_ref}' not in decisions`,
      );
    }
  }

  for (const risk of p.planning_context.known_risks) {
    if (risk.decision_ref && !decisionIds.has(risk.decision_ref)) {
      errors.push(`risk ${risk.id}.decision_ref '${risk.decision_ref}' not in decisions`);
    }
  }

  // Milestone references in DiagramGraph.scope are validated against
  // plan.milestones for referential integrity. Prevents orphaned diagrams
  // when milestones are merged or deleted.
  for (const diag of p.diagram_graphs) {
    if (diag.scope.startsWith("milestone:")) {
      const milestoneId = diag.scope.substring("milestone:".length);
      if (!milestoneIds.has(milestoneId)) {
        errors.push(
          `diagram ${diag.id}.scope '${diag.scope}' references unknown milestone`,
        );
      }
    }

    const nodeIds = new Set(diag.nodes.map((n) => n.id));
    for (const edge of diag.edges) {
      if (!nodeIds.has(edge.source)) {
        errors.push(`diagram ${diag.id} edge source '${edge.source}' not in nodes`);
      }
      if (!nodeIds.has(edge.target)) {
        errors.push(`diagram ${diag.id} edge target '${edge.target}' not in nodes`);
      }
    }
  }

  return { ok: errors.length === 0, errors };
}

export function validateDiagramScope(scope: string): ValidationResult {
  const errors: string[] = [];
  if (
    scope !== "overview" &&
    scope !== "invisible_knowledge" &&
    !scope.startsWith("milestone:")
  ) {
    errors.push(
      `diagram scope must be 'overview', 'invisible_knowledge', or 'milestone:M-XXX', got '${scope}'`,
    );
  }
  return { ok: errors.length === 0, errors };
}

export function validatePlanCode(p: Plan): ValidationResult {
  const errors: string[] = [];
  for (const m of p.milestones) {
    const changeIntents = new Set(
      m.code_changes.map((cc) => cc.intent_ref).filter((r) => r !== null),
    );
    for (const ci of m.code_intents) {
      if (!changeIntents.has(ci.id)) {
        errors.push(`milestone ${m.id} intent ${ci.id} has no corresponding code_change`);
      }
    }
  }
  return { ok: errors.length === 0, errors };
}

export function validatePlanDocs(p: Plan): ValidationResult {
  const errors: string[] = [];
  for (const m of p.milestones) {
    for (const cc of m.code_changes) {
      if (cc.diff.trim().length > 0 && cc.doc_diff.trim().length === 0) {
        errors.push(`milestone ${m.id} change ${cc.id} has diff but no doc_diff`);
      }
    }
  }
  return { ok: errors.length === 0, errors };
}

// Reads plan.json from planDir and runs validatePlanDesign + validateRefs.
// Returns { ok: false, errors } on read/parse failure or any validation failure.
export async function loadAndValidatePlan(
  planDir: string,
  log: Logger,
): Promise<{ ok: boolean; errors?: string[] }> {
  const planPath = path.join(planDir, "plan.json");
  let plan;
  try {
    const raw = await fs.readFile(planPath, "utf8");
    plan = JSON.parse(raw);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    log("Failed to read plan.json for validation", { error: message });
    return { ok: false, errors: [`Failed to read plan.json: ${message}`] };
  }

  const designValidation = validatePlanDesign(plan);
  if (!designValidation.ok) {
    log("Plan design validation failed", { errors: designValidation.errors });
    return { ok: false, errors: designValidation.errors };
  }

  const refValidation = validateRefs(plan);
  if (!refValidation.ok) {
    log("Plan reference validation failed", { errors: refValidation.errors });
    return { ok: false, errors: refValidation.errors };
  }

  log("Plan validation passed", { path: planPath });
  return { ok: true };
}
