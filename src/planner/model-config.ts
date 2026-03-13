// Koan config persistence for role-based model tier overrides.
// Storage location: ~/.koan/config.json under a `modelTiers` key.
// All 3 tiers (strong, standard, cheap) must be present when a config exists.
// Partial configs are treated as absent and logged.

import { promises as fs } from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

import { ALL_MODEL_TIERS, isModelTier, type ModelTier } from "./model-phase.js";
import { createLogger } from "../utils/logger.js";

const log = createLogger("model-config");

export const CONFIG_PATH = path.join(os.homedir(), ".koan", "config.json");

export type ModelTierConfig = Record<ModelTier, string>;

interface KoanConfigFile {
  modelTiers?: Record<string, string>;
  [key: string]: unknown;
}

export async function loadModelTierConfig(): Promise<ModelTierConfig | null> {
  let raw: string;
  try {
    raw = await fs.readFile(CONFIG_PATH, "utf8");
  } catch {
    return null;
  }

  let parsed: KoanConfigFile;
  try {
    parsed = JSON.parse(raw) as KoanConfigFile;
  } catch {
    log("config.json is not valid JSON; treating model tier config as absent.");
    return null;
  }

  if (!parsed.modelTiers || typeof parsed.modelTiers !== "object") {
    return null;
  }

  const modelTiers = parsed.modelTiers;
  const keys = Object.keys(modelTiers);

  if (keys.length !== ALL_MODEL_TIERS.length) {
    log(`config.json modelTiers has ${keys.length} entries (expected ${ALL_MODEL_TIERS.length}); treating as absent.`);
    return null;
  }

  const result: Partial<ModelTierConfig> = {};
  for (const tier of ALL_MODEL_TIERS) {
    if (!(tier in modelTiers)) {
      log(`config.json modelTiers is missing key "${tier}"; treating as absent.`);
      return null;
    }
    const value = modelTiers[tier];
    if (typeof value !== "string" || value.length === 0) {
      log(`config.json modelTiers["${tier}"] is not a non-empty string; treating as absent.`);
      return null;
    }
    result[tier] = value;
  }

  for (const key of keys) {
    if (!isModelTier(key)) {
      log(`config.json modelTiers contains unknown key "${key}"; treating as absent.`);
      return null;
    }
  }

  return result as ModelTierConfig;
}

export async function saveModelTierConfig(config: ModelTierConfig): Promise<void> {
  const configDir = path.dirname(CONFIG_PATH);
  await fs.mkdir(configDir, { recursive: true });

  let existing: KoanConfigFile = {};
  try {
    const raw = await fs.readFile(CONFIG_PATH, "utf8");
    existing = JSON.parse(raw) as KoanConfigFile;
  } catch {
    // Start fresh if file is missing or contains invalid JSON.
  }

  existing.modelTiers = config as Record<string, string>;

  const tmpPath = `${CONFIG_PATH}.tmp`;
  await fs.writeFile(tmpPath, `${JSON.stringify(existing, null, 2)}\n`, "utf8");
  await fs.rename(tmpPath, CONFIG_PATH);
}
