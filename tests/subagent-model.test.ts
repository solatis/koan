import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { buildSpawnArgs } from "../src/planner/subagent.js";
import {
  ALL_PHASE_MODEL_KEYS,
  type PhaseModelKey,
} from "../src/planner/model-phase.js";
import {
  applyGeneralPurposeModel,
  applyStrongModel,
  initConfigFromActiveModel,
} from "../src/planner/ui/config/model-selection.js";
import {
  GENERAL_PURPOSE_PHASE_MODEL_KEYS,
  STRONG_PHASE_MODEL_KEYS,
} from "../src/planner/model-phase.js";

// -- buildSpawnArgs: --model flag threading --

describe("buildSpawnArgs", () => {
  const baseOpts = {
    planDir: "/plan",
    subagentDir: "/subagent",
    extensionPath: "/ext/koan.ts",
    cwd: "/working",
  };

  it("omits --model flag when modelOverride is absent", () => {
    const args = buildSpawnArgs("architect", "plan-design", "start", baseOpts);
    assert.equal(args.includes("--model"), false);
  });

  it("omits --model flag when modelOverride is undefined", () => {
    const args = buildSpawnArgs("architect", "plan-design", "start", {
      ...baseOpts,
      modelOverride: undefined,
    });
    assert.equal(args.includes("--model"), false);
  });

  it("includes --model flag and value when modelOverride is set", () => {
    const args = buildSpawnArgs("architect", "plan-design", "start", {
      ...baseOpts,
      modelOverride: "anthropic/claude-opus-4",
    });
    assert.ok(args.includes("--model"), "expected --model flag in args");
    const idx = args.indexOf("--model");
    assert.equal(args[idx + 1], "anthropic/claude-opus-4");
  });

  it("places --model before the prompt (last arg)", () => {
    const prompt = "Begin the plan-design phase.";
    const args = buildSpawnArgs("architect", "plan-design", prompt, {
      ...baseOpts,
      modelOverride: "openai/gpt-5",
    });
    const modelIdx = args.indexOf("--model");
    const promptIdx = args.indexOf(prompt);
    assert.ok(modelIdx >= 0, "--model not found");
    assert.ok(promptIdx >= 0, "prompt not found");
    assert.ok(modelIdx < promptIdx, "--model should appear before prompt");
  });

  it("places --model after extraFlags", () => {
    const args = buildSpawnArgs("reviewer", "qr-plan-design", "Verify.", {
      ...baseOpts,
      extraFlags: ["--koan-qr-item", "item-42"],
      modelOverride: "google/gemini-2-pro",
    });
    const qrItemIdx = args.indexOf("--koan-qr-item");
    const modelIdx = args.indexOf("--model");
    assert.ok(qrItemIdx >= 0, "--koan-qr-item not found");
    assert.ok(modelIdx >= 0, "--model not found");
    assert.ok(qrItemIdx < modelIdx, "--model should appear after extra flags");
  });

  it("preserves all required fixed args regardless of modelOverride", () => {
    const args = buildSpawnArgs("developer", "plan-code", "begin", {
      ...baseOpts,
      modelOverride: "anthropic/claude-sonnet",
    });
    assert.ok(args.includes("-p"), "-p flag missing");
    assert.ok(args.includes("-e"), "-e flag missing");
    assert.ok(args.includes("--koan-role"), "--koan-role missing");
    assert.ok(args.includes("--koan-phase"), "--koan-phase missing");
    assert.ok(args.includes("--koan-plan-dir"), "--koan-plan-dir missing");
    assert.ok(args.includes("--koan-subagent-dir"), "--koan-subagent-dir missing");
  });
});

// -- Quick-set utility functions --

describe("initConfigFromActiveModel", () => {
  it("creates a 20-key config with all keys set to the given model", () => {
    const config = initConfigFromActiveModel("anthropic/claude-sonnet");
    assert.equal(Object.keys(config).length, ALL_PHASE_MODEL_KEYS.length);
    for (const key of ALL_PHASE_MODEL_KEYS) {
      assert.equal(config[key], "anthropic/claude-sonnet", `key ${key} should be set`);
    }
  });

  it("produces a config where all values are the same model", () => {
    const config = initConfigFromActiveModel("openai/gpt-5");
    const values = Object.values(config);
    assert.ok(values.every((v) => v === "openai/gpt-5"));
  });
});

describe("applyStrongModel", () => {
  it("sets all strong keys to the chosen model, leaving GP keys from existing config", () => {
    const existing = initConfigFromActiveModel("openai/gpt-4");
    const result = applyStrongModel("anthropic/claude-opus-4", existing, "openai/gpt-4");

    for (const key of STRONG_PHASE_MODEL_KEYS) {
      assert.equal(result[key], "anthropic/claude-opus-4", `strong key ${key} should be updated`);
    }

    for (const key of GENERAL_PURPOSE_PHASE_MODEL_KEYS) {
      assert.equal(result[key], "openai/gpt-4", `GP key ${key} should be unchanged`);
    }
  });

  it("initializes from activeModelId when existingConfig is null", () => {
    const result = applyStrongModel("anthropic/claude-opus-4", null, "openai/gpt-5-mini");

    for (const key of STRONG_PHASE_MODEL_KEYS) {
      assert.equal(result[key], "anthropic/claude-opus-4", `strong key ${key} should be updated`);
    }

    for (const key of GENERAL_PURPOSE_PHASE_MODEL_KEYS) {
      assert.equal(result[key], "openai/gpt-5-mini", `GP key ${key} should be initialized from active model`);
    }
  });

  it("writes all 20 keys regardless of which keys are strong", () => {
    const result = applyStrongModel("some/model", null, "active/model");
    assert.equal(Object.keys(result).length, ALL_PHASE_MODEL_KEYS.length);
  });
});

describe("applyGeneralPurposeModel", () => {
  it("sets all GP keys to the chosen model, leaving strong keys from existing config", () => {
    const existing = initConfigFromActiveModel("anthropic/claude-opus-4");
    const result = applyGeneralPurposeModel("openai/gpt-5-mini", existing, "anthropic/claude-opus-4");

    for (const key of GENERAL_PURPOSE_PHASE_MODEL_KEYS) {
      assert.equal(result[key], "openai/gpt-5-mini", `GP key ${key} should be updated`);
    }

    for (const key of STRONG_PHASE_MODEL_KEYS) {
      assert.equal(result[key], "anthropic/claude-opus-4", `strong key ${key} should be unchanged`);
    }
  });

  it("initializes from activeModelId when existingConfig is null", () => {
    const result = applyGeneralPurposeModel("openai/gpt-5-mini", null, "anthropic/claude-sonnet");

    for (const key of GENERAL_PURPOSE_PHASE_MODEL_KEYS) {
      assert.equal(result[key], "openai/gpt-5-mini", `GP key ${key} should be updated`);
    }

    for (const key of STRONG_PHASE_MODEL_KEYS) {
      assert.equal(result[key], "anthropic/claude-sonnet", `strong key ${key} should be initialized from active model`);
    }
  });

  it("writes all 20 keys regardless of which keys are GP", () => {
    const result = applyGeneralPurposeModel("some/model", null, "active/model");
    assert.equal(Object.keys(result).length, ALL_PHASE_MODEL_KEYS.length);
  });
});

describe("quick-set from empty config: all-or-none persistence invariant", () => {
  it("applyStrongModel from null config produces a 20-key config (all-or-none)", () => {
    const result = applyStrongModel("strong/model", null, "active/model");
    const keys = Object.keys(result) as PhaseModelKey[];
    assert.equal(keys.length, ALL_PHASE_MODEL_KEYS.length);

    // Verify every expected key is present
    for (const key of ALL_PHASE_MODEL_KEYS) {
      assert.ok(key in result, `key "${key}" missing from result`);
      assert.equal(typeof result[key], "string");
      assert.ok(result[key].length > 0);
    }
  });

  it("applyGeneralPurposeModel from null config produces a 20-key config (all-or-none)", () => {
    const result = applyGeneralPurposeModel("gp/model", null, "active/model");
    const keys = Object.keys(result) as PhaseModelKey[];
    assert.equal(keys.length, ALL_PHASE_MODEL_KEYS.length);

    for (const key of ALL_PHASE_MODEL_KEYS) {
      assert.ok(key in result, `key "${key}" missing from result`);
    }
  });

  it("strong and GP quick-set results are complementary", () => {
    const activeModel = "active/model";

    const strongResult = applyStrongModel("strong/model", null, activeModel);
    const gpResult = applyGeneralPurposeModel("gp/model", null, activeModel);

    // Strong keys in strongResult should differ from GP keys
    for (const key of STRONG_PHASE_MODEL_KEYS) {
      assert.equal(strongResult[key], "strong/model");
      assert.equal(gpResult[key], activeModel); // GP result left strong keys as active
    }

    for (const key of GENERAL_PURPOSE_PHASE_MODEL_KEYS) {
      assert.equal(strongResult[key], activeModel); // strong result left GP keys as active
      assert.equal(gpResult[key], "gp/model");
    }
  });
});
