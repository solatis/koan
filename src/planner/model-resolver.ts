// Spawn-time model resolver for role-based model overrides.
// Maps SubagentRole → ModelTier → configured model string.
// Returns undefined when no config exists so the caller omits --model,
// preserving pi's current active model as the implicit fallback.

import { ROLE_MODEL_TIER, type SubagentRole } from "./types.js";
import { loadModelTierConfig } from "./model-config.js";

export async function resolveModelForRole(role: SubagentRole): Promise<string | undefined> {
  const config = await loadModelTierConfig();
  if (config === null) return undefined;
  const tier = ROLE_MODEL_TIER[role];
  return config[tier];
}
