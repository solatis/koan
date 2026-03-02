import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  ALL_PHASE_MODEL_KEYS,
  GENERAL_PURPOSE_PHASE_MODEL_KEYS,
  PHASE_ROWS,
  STRONG_PHASE_MODEL_KEYS,
  SUB_PHASES,
  buildPhaseModelKey,
  isPhaseModelKey,
  type PhaseModelKey,
} from "../src/planner/model-phase.js";

describe("ALL_PHASE_MODEL_KEYS", () => {
  it("contains exactly 20 keys (5 rows × 4 sub-phases)", () => {
    assert.equal(ALL_PHASE_MODEL_KEYS.length, PHASE_ROWS.length * SUB_PHASES.length);
    assert.equal(ALL_PHASE_MODEL_KEYS.length, 20);
  });

  it("contains no duplicates", () => {
    const set = new Set(ALL_PHASE_MODEL_KEYS);
    assert.equal(set.size, ALL_PHASE_MODEL_KEYS.length);
  });

  it("contains every combination of row and sub-phase", () => {
    for (const row of PHASE_ROWS) {
      for (const sub of SUB_PHASES) {
        const key = `${row}-${sub}` as PhaseModelKey;
        assert.ok(
          ALL_PHASE_MODEL_KEYS.includes(key),
          `expected key "${key}" to be present`,
        );
      }
    }
  });
});

describe("STRONG_PHASE_MODEL_KEYS", () => {
  it("contains exactly 9 keys", () => {
    assert.equal(STRONG_PHASE_MODEL_KEYS.size, 9);
  });

  it("contains all 5 qr-decompose keys", () => {
    for (const row of PHASE_ROWS) {
      const key = buildPhaseModelKey(row, "qr-decompose");
      assert.ok(STRONG_PHASE_MODEL_KEYS.has(key), `expected ${key} to be strong`);
    }
  });

  it("contains plan-design exec-debut and exec-fix", () => {
    assert.ok(STRONG_PHASE_MODEL_KEYS.has("plan-design-exec-debut"));
    assert.ok(STRONG_PHASE_MODEL_KEYS.has("plan-design-exec-fix"));
  });

  it("contains exec-docs exec-debut and exec-fix", () => {
    assert.ok(STRONG_PHASE_MODEL_KEYS.has("exec-docs-exec-debut"));
    assert.ok(STRONG_PHASE_MODEL_KEYS.has("exec-docs-exec-fix"));
  });

  it("does not contain plan-code or plan-docs exec keys", () => {
    assert.equal(STRONG_PHASE_MODEL_KEYS.has("plan-code-exec-debut"), false);
    assert.equal(STRONG_PHASE_MODEL_KEYS.has("plan-code-exec-fix"), false);
    assert.equal(STRONG_PHASE_MODEL_KEYS.has("plan-docs-exec-debut"), false);
    assert.equal(STRONG_PHASE_MODEL_KEYS.has("plan-docs-exec-fix"), false);
  });
});

describe("GENERAL_PURPOSE_PHASE_MODEL_KEYS", () => {
  it("contains exactly 11 keys (20 total - 9 strong)", () => {
    assert.equal(GENERAL_PURPOSE_PHASE_MODEL_KEYS.length, 11);
  });

  it("strong and GP form a complete partition of all keys", () => {
    const strongSet = STRONG_PHASE_MODEL_KEYS;
    const gpSet = new Set(GENERAL_PURPOSE_PHASE_MODEL_KEYS);

    // Union equals ALL
    for (const key of ALL_PHASE_MODEL_KEYS) {
      assert.ok(
        strongSet.has(key) || gpSet.has(key),
        `key "${key}" missing from both sets`,
      );
    }

    // Intersection is empty
    for (const key of ALL_PHASE_MODEL_KEYS) {
      assert.equal(
        strongSet.has(key) && gpSet.has(key),
        false,
        `key "${key}" appears in both sets`,
      );
    }
  });
});

describe("isPhaseModelKey", () => {
  it("returns true for valid keys", () => {
    for (const key of ALL_PHASE_MODEL_KEYS) {
      assert.equal(isPhaseModelKey(key), true, `expected "${key}" to be valid`);
    }
  });

  it("returns false for invalid strings", () => {
    assert.equal(isPhaseModelKey("plan-design"), false);
    assert.equal(isPhaseModelKey("exec-debut"), false);
    assert.equal(isPhaseModelKey("plan-design-exec-init"), false);
    assert.equal(isPhaseModelKey("unknown-key"), false);
    assert.equal(isPhaseModelKey(""), false);
  });

  it("returns false for non-string values", () => {
    assert.equal(isPhaseModelKey(42), false);
    assert.equal(isPhaseModelKey(null), false);
    assert.equal(isPhaseModelKey(undefined), false);
    assert.equal(isPhaseModelKey({}), false);
  });
});

describe("buildPhaseModelKey", () => {
  it("produces correct key for all combinations", () => {
    assert.equal(buildPhaseModelKey("plan-design", "exec-debut"), "plan-design-exec-debut");
    assert.equal(buildPhaseModelKey("exec-docs", "qr-verify"), "exec-docs-qr-verify");
    assert.equal(buildPhaseModelKey("plan-code", "qr-decompose"), "plan-code-qr-decompose");
  });

  it("produces keys that pass isPhaseModelKey", () => {
    for (const row of PHASE_ROWS) {
      for (const sub of SUB_PHASES) {
        const key = buildPhaseModelKey(row, sub);
        assert.equal(isPhaseModelKey(key), true, `buildPhaseModelKey(${row}, ${sub}) = "${key}" failed isPhaseModelKey`);
      }
    }
  });
});
