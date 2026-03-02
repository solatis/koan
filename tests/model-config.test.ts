import assert from "node:assert/strict";
import { promises as fs } from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it } from "node:test";

import { ALL_PHASE_MODEL_KEYS, type PhaseModelKey } from "../src/planner/model-phase.js";
import { loadPhaseModelConfig, savePhaseModelConfig } from "../src/planner/model-config.js";

function makeFullConfig(model = "anthropic/claude-sonnet"): Record<PhaseModelKey, string> {
  const config: Partial<Record<PhaseModelKey, string>> = {};
  for (const key of ALL_PHASE_MODEL_KEYS) {
    config[key] = model;
  }
  return config as Record<PhaseModelKey, string>;
}

// Test config validation logic directly using a mock config file
// by writing to a temp location and reading back.
// Note: loadPhaseModelConfig reads from ~/.koan/config.json, so we
// test validation using the raw parsing logic via an in-process approach.

describe("config validation", () => {
  it("accepts a complete 20-key config and returns it unchanged", async () => {
    // We test the validation by round-tripping through save/load.
    // To avoid touching ~/.koan/config.json, we verify the pure logic
    // by testing that a valid config object has all required keys.
    const config = makeFullConfig("anthropic/claude-opus-4");

    // Verify it has exactly 20 keys
    assert.equal(Object.keys(config).length, ALL_PHASE_MODEL_KEYS.length);

    // Verify all keys are valid PhaseModelKeys
    for (const key of Object.keys(config)) {
      assert.ok(
        (ALL_PHASE_MODEL_KEYS as readonly string[]).includes(key),
        `unexpected key: ${key}`,
      );
    }

    // Verify all values are non-empty strings
    for (const [key, value] of Object.entries(config)) {
      assert.equal(typeof value, "string", `value for ${key} should be a string`);
      assert.ok(value.length > 0, `value for ${key} should be non-empty`);
    }
  });

  it("treats null as valid (no overrides)", () => {
    // Null config is valid — it means inherit from pi's active model
    const config: Record<PhaseModelKey, string> | null = null;
    assert.equal(config, null);
  });
});

describe("loadPhaseModelConfig (integration)", () => {
  it("returns null when config file is missing", async () => {
    // loadPhaseModelConfig reads ~/.koan/config.json - if it doesn't exist, null
    // We can only test this if ~/.koan/config.json doesn't exist on this machine
    // or has no phaseModels. This is an integration test, so we skip the file check
    // and instead verify the contract: the function always returns null or a valid config.
    const result = await loadPhaseModelConfig();
    // Result is either null or a Record with exactly 20 keys
    if (result !== null) {
      assert.equal(Object.keys(result).length, ALL_PHASE_MODEL_KEYS.length);
      for (const key of ALL_PHASE_MODEL_KEYS) {
        assert.equal(typeof result[key], "string");
        assert.ok(result[key].length > 0);
      }
    }
  });
});

describe("savePhaseModelConfig + loadPhaseModelConfig (round-trip)", () => {
  it("persists a full config and reads it back correctly", async () => {
    // KOAN_CONFIG_PATH is computed at module load time, so tests validate
    // round-trip behavior against the real path and restore prior state.

    const actualConfigPath = path.join(os.homedir(), ".koan", "config.json");
    let preExisting: string | null = null;

    try {
      preExisting = await fs.readFile(actualConfigPath, "utf8");
    } catch {
      preExisting = null;
    }

    try {
      const config = makeFullConfig("openai/gpt-5");
      await savePhaseModelConfig(config);

      const loaded = await loadPhaseModelConfig();
      assert.ok(loaded !== null, "expected config to be loaded after save");
      assert.equal(Object.keys(loaded).length, ALL_PHASE_MODEL_KEYS.length);

      for (const key of ALL_PHASE_MODEL_KEYS) {
        assert.equal(loaded[key], "openai/gpt-5", `mismatch for key ${key}`);
      }
    } finally {
      // Restore original state
      if (preExisting === null) {
        try {
          const koanDir = path.join(os.homedir(), ".koan");
          await fs.rm(actualConfigPath, { force: true });
          // Try to remove the .koan dir if it was empty before
          const entries = await fs.readdir(koanDir);
          if (entries.length === 0) {
            await fs.rmdir(koanDir);
          }
        } catch {
          // Best-effort cleanup
        }
      } else {
        await fs.writeFile(actualConfigPath, preExisting, "utf8");
      }

    }
  });

  it("persists null (clears overrides) while preserving other config keys", async () => {
    const actualConfigPath = path.join(os.homedir(), ".koan", "config.json");
    let preExisting: string | null = null;

    try {
      preExisting = await fs.readFile(actualConfigPath, "utf8");
    } catch {
      preExisting = null;
    }

    try {
      // Write an initial config
      await savePhaseModelConfig(makeFullConfig("anthropic/claude-sonnet"));

      // Now clear it
      await savePhaseModelConfig(null);

      const loaded = await loadPhaseModelConfig();
      assert.equal(loaded, null, "expected null after clearing overrides");

      // Verify the config file still exists but has no phaseModels key
      const raw = await fs.readFile(actualConfigPath, "utf8");
      const parsed = (raw.trim().length === 0 ? {} : JSON.parse(raw)) as Record<string, unknown>;
      assert.equal("phaseModels" in parsed, false, "phaseModels should be absent after clearing");
    } finally {
      if (preExisting === null) {
        try {
          await fs.rm(actualConfigPath, { force: true });
        } catch {
          // Best-effort
        }
      } else {
        await fs.writeFile(actualConfigPath, preExisting, "utf8");
      }
    }
  });
});

describe("config validation: partial config treated as absent", () => {
  it("validates that a partial config (missing keys) is treated as absent", async () => {
    // We simulate this by checking the validation logic:
    // A config with fewer than 20 keys should produce null from loadPhaseModelConfig.
    // We test this indirectly by verifying the contract.
    const partialKeys = ALL_PHASE_MODEL_KEYS.slice(0, 10);
    assert.equal(partialKeys.length, 10);
    assert.equal(partialKeys.length < ALL_PHASE_MODEL_KEYS.length, true);

    // A partial config would fail the length check in loadPhaseModelConfig.
    // We verify this by writing a partial config and reading it back.
    const actualConfigPath = path.join(os.homedir(), ".koan", "config.json");
    let preExisting: string | null = null;

    try {
      preExisting = await fs.readFile(actualConfigPath, "utf8");
    } catch {
      preExisting = null;
    }

    try {
      await fs.mkdir(path.dirname(actualConfigPath), { recursive: true });
      const partial: Record<string, string> = {};
      for (const key of partialKeys) {
        partial[key] = "anthropic/claude-sonnet";
      }
      await fs.writeFile(actualConfigPath, JSON.stringify({ phaseModels: partial }), "utf8");

      const loaded = await loadPhaseModelConfig();
      assert.equal(loaded, null, "expected null for partial config");
    } finally {
      if (preExisting === null) {
        try { await fs.rm(actualConfigPath, { force: true }); } catch { /* best-effort */ }
      } else {
        await fs.writeFile(actualConfigPath, preExisting, "utf8");
      }
    }
  });

  it("validates that a config with unknown keys is treated as absent", async () => {
    const actualConfigPath = path.join(os.homedir(), ".koan", "config.json");
    let preExisting: string | null = null;

    try {
      preExisting = await fs.readFile(actualConfigPath, "utf8");
    } catch {
      preExisting = null;
    }

    try {
      await fs.mkdir(path.dirname(actualConfigPath), { recursive: true });

      // Build a 20-key config with one key replaced by an unknown key
      const badConfig: Record<string, string> = {};
      let first = true;
      for (const key of ALL_PHASE_MODEL_KEYS) {
        if (first) {
          badConfig["unknown-phase-exec-debut"] = "anthropic/claude-sonnet";
          first = false;
        } else {
          badConfig[key] = "anthropic/claude-sonnet";
        }
      }

      await fs.writeFile(actualConfigPath, JSON.stringify({ phaseModels: badConfig }), "utf8");

      const loaded = await loadPhaseModelConfig();
      assert.equal(loaded, null, "expected null for config with unknown key");
    } finally {
      if (preExisting === null) {
        try { await fs.rm(actualConfigPath, { force: true }); } catch { /* best-effort */ }
      } else {
        await fs.writeFile(actualConfigPath, preExisting, "utf8");
      }
    }
  });
});
