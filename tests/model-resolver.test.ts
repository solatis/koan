import assert from "node:assert/strict";
import { promises as fs } from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, it } from "node:test";

import {
  ALL_PHASE_MODEL_KEYS,
  PHASE_ROWS,
  SUB_PHASES,
  type PhaseModelKey,
} from "../src/planner/model-phase.js";
import {
  mapSpawnContextToPhaseModelKey,
  resolvePhaseModelOverride,
  type SpawnContext,
} from "../src/planner/model-resolver.js";

describe("mapSpawnContextToPhaseModelKey", () => {
  it("maps work-debut to exec-debut for all phase rows", () => {
    for (const row of PHASE_ROWS) {
      const key = mapSpawnContextToPhaseModelKey("work-debut", row);
      assert.equal(key, `${row}-exec-debut`, `row=${row}`);
    }
  });

  it("maps fix to exec-fix for all phase rows", () => {
    for (const row of PHASE_ROWS) {
      const key = mapSpawnContextToPhaseModelKey("fix", row);
      assert.equal(key, `${row}-exec-fix`, `row=${row}`);
    }
  });

  it("maps qr-decompose to qr-decompose for all phase rows", () => {
    for (const row of PHASE_ROWS) {
      const key = mapSpawnContextToPhaseModelKey("qr-decompose", row);
      assert.equal(key, `${row}-qr-decompose`, `row=${row}`);
    }
  });

  it("maps qr-verify to qr-verify for all phase rows", () => {
    for (const row of PHASE_ROWS) {
      const key = mapSpawnContextToPhaseModelKey("qr-verify", row);
      assert.equal(key, `${row}-qr-verify`, `row=${row}`);
    }
  });

  it("produces keys that are valid PhaseModelKeys", () => {
    const contexts: SpawnContext[] = ["work-debut", "fix", "qr-decompose", "qr-verify"];
    for (const context of contexts) {
      for (const row of PHASE_ROWS) {
        const key = mapSpawnContextToPhaseModelKey(context, row);
        assert.ok(
          (ALL_PHASE_MODEL_KEYS as readonly string[]).includes(key),
          `key "${key}" (context=${context}, row=${row}) is not a valid PhaseModelKey`,
        );
      }
    }
  });

  it("covers all 20 PhaseModelKeys across context × row combinations", () => {
    const produced = new Set<PhaseModelKey>();
    const contexts: SpawnContext[] = ["work-debut", "fix", "qr-decompose", "qr-verify"];
    for (const context of contexts) {
      for (const row of PHASE_ROWS) {
        produced.add(mapSpawnContextToPhaseModelKey(context, row));
      }
    }
    assert.equal(produced.size, ALL_PHASE_MODEL_KEYS.length);
    for (const key of ALL_PHASE_MODEL_KEYS) {
      assert.ok(produced.has(key), `key "${key}" not produced by any context × row combination`);
    }
  });

  it("accepts optional fixPhase argument without altering output", () => {
    const withoutFix = mapSpawnContextToPhaseModelKey("fix", "plan-design");
    const withFix = mapSpawnContextToPhaseModelKey("fix", "plan-design", "plan-design");
    assert.equal(withoutFix, withFix);
  });
});

describe("SpawnContext values cover all sub-phases", () => {
  it("one SpawnContext maps to each SubPhase", () => {
    const contexts: SpawnContext[] = ["work-debut", "fix", "qr-decompose", "qr-verify"];
    const row = "plan-design";
    const subPhasesProduced = contexts.map((c) => {
      const key = mapSpawnContextToPhaseModelKey(c, row);
      return key.replace(`${row}-`, "") as typeof SUB_PHASES[number];
    });

    for (const sub of SUB_PHASES) {
      assert.ok(
        subPhasesProduced.includes(sub),
        `sub-phase "${sub}" not covered by any SpawnContext`,
      );
    }
  });
});

function makeFullConfig(model: string): Record<PhaseModelKey, string> {
  const config: Partial<Record<PhaseModelKey, string>> = {};
  for (const key of ALL_PHASE_MODEL_KEYS) {
    config[key] = model;
  }
  return config as Record<PhaseModelKey, string>;
}

async function withConfigFile<T>(
  setup: (configPath: string) => Promise<void>,
  run: () => Promise<T>,
): Promise<T> {
  const configPath = path.join(os.homedir(), ".koan", "config.json");

  let preExisting: string | null = null;
  try {
    preExisting = await fs.readFile(configPath, "utf8");
  } catch {
    preExisting = null;
  }

  try {
    await fs.mkdir(path.dirname(configPath), { recursive: true });
    await setup(configPath);
    return await run();
  } finally {
    if (preExisting === null) {
      try {
        await fs.rm(configPath, { force: true });
      } catch {
        // best-effort cleanup
      }
    } else {
      await fs.writeFile(configPath, preExisting, "utf8");
    }
  }
}

describe("resolvePhaseModelOverride", () => {
  it("returns configured model when full config is present", async () => {
    await withConfigFile(
      async (configPath) => {
        const phaseModels = makeFullConfig("anthropic/claude-sonnet");
        phaseModels["plan-design-exec-debut"] = "openai/gpt-5";
        await fs.writeFile(configPath, `${JSON.stringify({ phaseModels }, null, 2)}\n`, "utf8");
      },
      async () => {
        const value = await resolvePhaseModelOverride("plan-design-exec-debut");
        assert.equal(value, "openai/gpt-5");
      },
    );
  });

  it("returns undefined when config is absent", async () => {
    await withConfigFile(
      async (configPath) => {
        await fs.writeFile(configPath, `${JSON.stringify({ unrelated: true }, null, 2)}\n`, "utf8");
      },
      async () => {
        const value = await resolvePhaseModelOverride("plan-code-exec-fix");
        assert.equal(value, undefined);
      },
    );
  });
});
