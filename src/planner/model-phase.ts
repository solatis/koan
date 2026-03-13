// Role-based model tier types for koan.
// Replaces the old 5×4 PhaseRow × SubPhase matrix with a 3-tier system.
// Tiers map deterministically from role via ROLE_MODEL_TIER in types.ts.

import type { ModelTier } from "./types.js";

export type { ModelTier, SubagentRole } from "./types.js";
export { ROLE_MODEL_TIER } from "./types.js";

export const ALL_MODEL_TIERS: readonly ModelTier[] = ["strong", "standard", "cheap"];

export function isModelTier(value: unknown): value is ModelTier {
  return typeof value === "string" && ALL_MODEL_TIERS.includes(value as ModelTier);
}
