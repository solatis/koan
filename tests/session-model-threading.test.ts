import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  resolveSpawnModelOverride,
  spawnWorkWithResolvedModel,
  spawnFixWithResolvedModel,
  spawnQRDecomposerWithResolvedModel,
  spawnReviewerWithResolvedModel,
} from "../src/planner/session.js";
import type { PhaseModelKey } from "../src/planner/model-phase.js";

describe("resolveSpawnModelOverride", () => {
  it("maps context -> key and resolves override", async () => {
    const contexts = ["work-debut", "fix", "qr-decompose", "qr-verify"] as const;

    for (const context of contexts) {
      let mappedContext: string | null = null;
      let mappedRow: string | null = null;
      let resolvedKey: string | null = null;

      const result = await resolveSpawnModelOverride(context, "plan-design", {
        mapSpawnContextToPhaseModelKeyFn: (ctx, row) => {
          mappedContext = ctx;
          mappedRow = row;
          return "plan-design-exec-debut" as PhaseModelKey;
        },
        resolvePhaseModelOverrideFn: async (key) => {
          resolvedKey = key;
          return "anthropic/claude-opus-4";
        },
      });

      assert.equal(mappedContext, context);
      assert.equal(mappedRow, "plan-design");
      assert.equal(resolvedKey, "plan-design-exec-debut");
      assert.equal(result, "anthropic/claude-opus-4");
    }
  });

  it("returns undefined when resolver reports absent config", async () => {
    const result = await resolveSpawnModelOverride("work-debut", "plan-code", {
      mapSpawnContextToPhaseModelKeyFn: () => "plan-code-exec-debut" as PhaseModelKey,
      resolvePhaseModelOverrideFn: async () => undefined,
    });

    assert.equal(result, undefined);
  });
});

describe("work/fix spawn model threading", () => {
  it("threads resolved modelOverride into work spawns", async () => {
    let capturedModelOverride: string | undefined;

    await spawnWorkWithResolvedModel(
      "plan-design",
      async (opts) => {
        capturedModelOverride = opts.modelOverride;
        return { exitCode: 0, stderr: "", subagentDir: opts.subagentDir };
      },
      {
        planDir: "/plan",
        subagentDir: "/subagent",
        cwd: "/cwd",
        extensionPath: "/ext/koan.ts",
        log: () => {},
      },
      {
        mapSpawnContextToPhaseModelKeyFn: (ctx, row) => {
          assert.equal(ctx, "work-debut");
          assert.equal(row, "plan-design");
          return "plan-design-exec-debut" as PhaseModelKey;
        },
        resolvePhaseModelOverrideFn: async (key) => {
          assert.equal(key, "plan-design-exec-debut");
          return "anthropic/claude-opus-4";
        },
      },
    );

    assert.equal(capturedModelOverride, "anthropic/claude-opus-4");
  });

  it("threads resolved modelOverride into fix spawns", async () => {
    let capturedModelOverride: string | undefined;

    await spawnFixWithResolvedModel(
      "plan-code",
      async (opts) => {
        capturedModelOverride = opts.modelOverride;
        return { exitCode: 0, stderr: "", subagentDir: opts.subagentDir };
      },
      {
        planDir: "/plan",
        subagentDir: "/subagent",
        cwd: "/cwd",
        extensionPath: "/ext/koan.ts",
        log: () => {},
      },
      {
        mapSpawnContextToPhaseModelKeyFn: (ctx, row) => {
          assert.equal(ctx, "fix");
          assert.equal(row, "plan-code");
          return "plan-code-exec-fix" as PhaseModelKey;
        },
        resolvePhaseModelOverrideFn: async (key) => {
          assert.equal(key, "plan-code-exec-fix");
          return "openai/gpt-5";
        },
      },
    );

    assert.equal(capturedModelOverride, "openai/gpt-5");
  });
});

describe("QR spawn model threading", () => {
  it("threads resolved modelOverride into spawnQRDecomposer", async () => {
    let capturedModelOverride: string | undefined;

    await spawnQRDecomposerWithResolvedModel(
      {
        planDir: "/plan",
        subagentDir: "/subagent",
        cwd: "/cwd",
        extensionPath: "/ext/koan.ts",
        phase: "plan-design",
      },
      {
        mapSpawnContextToPhaseModelKeyFn: (ctx, row) => {
          assert.equal(ctx, "qr-decompose");
          assert.equal(row, "plan-design");
          return "plan-design-qr-decompose" as PhaseModelKey;
        },
        resolvePhaseModelOverrideFn: async (key) => {
          assert.equal(key, "plan-design-qr-decompose");
          return "openai/gpt-5";
        },
        spawnQRDecomposerFn: async (opts) => {
          capturedModelOverride = opts.modelOverride;
          return { exitCode: 0, stderr: "", subagentDir: opts.subagentDir };
        },
      },
    );

    assert.equal(capturedModelOverride, "openai/gpt-5");
  });

  it("threads resolved modelOverride into spawnReviewer", async () => {
    let capturedModelOverride: string | undefined;

    await spawnReviewerWithResolvedModel(
      {
        planDir: "/plan",
        subagentDir: "/subagent",
        cwd: "/cwd",
        extensionPath: "/ext/koan.ts",
        phase: "plan-code",
        itemId: "QR-001",
      },
      {
        mapSpawnContextToPhaseModelKeyFn: (ctx, row) => {
          assert.equal(ctx, "qr-verify");
          assert.equal(row, "plan-code");
          return "plan-code-qr-verify" as PhaseModelKey;
        },
        resolvePhaseModelOverrideFn: async (key) => {
          assert.equal(key, "plan-code-qr-verify");
          return "google/gemini-3-pro";
        },
        spawnReviewerFn: async (opts) => {
          capturedModelOverride = opts.modelOverride;
          return { exitCode: 0, stderr: "", subagentDir: opts.subagentDir };
        },
      },
    );

    assert.equal(capturedModelOverride, "google/gemini-3-pro");
  });

  it("passes undefined modelOverride when config is absent", async () => {
    let capturedModelOverride: string | undefined;

    await spawnReviewerWithResolvedModel(
      {
        planDir: "/plan",
        subagentDir: "/subagent",
        cwd: "/cwd",
        extensionPath: "/ext/koan.ts",
        phase: "plan-docs",
        itemId: "QR-002",
      },
      {
        mapSpawnContextToPhaseModelKeyFn: () => "plan-docs-qr-verify" as PhaseModelKey,
        resolvePhaseModelOverrideFn: async () => undefined,
        spawnReviewerFn: async (opts) => {
          capturedModelOverride = opts.modelOverride;
          return { exitCode: 0, stderr: "", subagentDir: opts.subagentDir };
        },
      },
    );

    assert.equal(capturedModelOverride, undefined);
  });
});
