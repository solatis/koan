import { test } from "node:test";
import * as assert from "node:assert/strict";

import { KOAN_DEBUG_FLAG } from "../src/planner/lib/constants.js";
import { buildSubagentArgs } from "../src/planner/subagent.js";

test("buildSubagentArgs debugMode:false does not include --koan-debug", () => {
  const args = buildSubagentArgs(
    "intake",
    "/tmp/subagent",
    "/tmp/ext/koan.ts",
    undefined,
    false,
  );

  assert.ok(!args.includes(`--${KOAN_DEBUG_FLAG}`));
});

test("buildSubagentArgs debugMode:true includes --koan-debug", () => {
  const args = buildSubagentArgs(
    "intake",
    "/tmp/subagent",
    "/tmp/ext/koan.ts",
    undefined,
    true,
  );

  assert.ok(args.includes(`--${KOAN_DEBUG_FLAG}`));
});

test("buildSubagentArgs includes model override when provided", () => {
  const args = buildSubagentArgs(
    "planner",
    "/tmp/subagent",
    "/tmp/ext/koan.ts",
    "provider/model-id",
    true,
  );

  const modelFlagIndex = args.indexOf("--model");
  assert.ok(modelFlagIndex >= 0, "--model flag should be present");
  assert.equal(args[modelFlagIndex + 1], "provider/model-id");
});
