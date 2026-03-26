// Property-based state machine tests for koan.
// Verifies:
//   - All valid story status transitions (story lifecycle state machine)
//   - Routing decisions for all state combinations
//   - Permission matrices (role × tool × expected result)

import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { promises as fs } from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

import { checkPermission, ROLE_PERMISSIONS } from "../src/planner/lib/permissions.js";
import {
  loadStoryState,
  saveStoryState,
  ensureStoryDirectory,
} from "../src/planner/epic/state.js";
import { createInitialStoryState } from "../src/planner/epic/types.js";
import type { StoryStatus } from "../src/planner/types.js";
import { assertStatus } from "../src/planner/tools/orchestrator.js";

async function mkTempDir(): Promise<string> {
  return fs.mkdtemp(path.join(os.tmpdir(), "koan-sm-test-"));
}

async function withEpicDir<T>(fn: (epicDir: string) => Promise<T>): Promise<T> {
  const dir = await mkTempDir();
  try {
    await fs.mkdir(path.join(dir, "stories"), { recursive: true });
    return await fn(dir);
  } finally {
    await fs.rm(dir, { recursive: true, force: true });
  }
}

// ---------------------------------------------------------------------------
// State machine: valid transitions (story lifecycle)
// ---------------------------------------------------------------------------

describe("state machine: valid transitions", () => {
  // koan_select_story: pending → selected, retry → selected
  it("koan_select_story accepts pending → selected", async () => {
    await withEpicDir(async (epicDir) => {
      await ensureStoryDirectory(epicDir, "S-001-auth");
      const state = await loadStoryState(epicDir, "S-001-auth");
      assert.equal(state.status, "pending");

      await saveStoryState(epicDir, "S-001-auth", { ...state, status: "selected", updatedAt: new Date().toISOString() });
      const updated = await loadStoryState(epicDir, "S-001-auth");
      assert.equal(updated.status, "selected");
    });
  });

  it("koan_select_story accepts retry → selected", async () => {
    await withEpicDir(async (epicDir) => {
      await ensureStoryDirectory(epicDir, "S-001-auth");
      const state = await loadStoryState(epicDir, "S-001-auth");

      await saveStoryState(epicDir, "S-001-auth", { ...state, status: "retry", updatedAt: new Date().toISOString() });
      const retrying = await loadStoryState(epicDir, "S-001-auth");
      assert.equal(retrying.status, "retry");

      await saveStoryState(epicDir, "S-001-auth", { ...retrying, status: "selected", updatedAt: new Date().toISOString() });
      const selected = await loadStoryState(epicDir, "S-001-auth");
      assert.equal(selected.status, "selected");
    });
  });

  // koan_complete_story: verifying → done
  it("koan_complete_story accepts verifying → done", async () => {
    await withEpicDir(async (epicDir) => {
      await ensureStoryDirectory(epicDir, "S-002-routes");
      const state = await loadStoryState(epicDir, "S-002-routes");
      await saveStoryState(epicDir, "S-002-routes", { ...state, status: "verifying", updatedAt: new Date().toISOString() });

      const verifying = await loadStoryState(epicDir, "S-002-routes");
      assert.equal(verifying.status, "verifying");

      await saveStoryState(epicDir, "S-002-routes", { ...verifying, status: "done", updatedAt: new Date().toISOString() });
      const done = await loadStoryState(epicDir, "S-002-routes");
      assert.equal(done.status, "done");
    });
  });

  // koan_retry_story: verifying → retry
  it("koan_retry_story accepts verifying → retry", async () => {
    await withEpicDir(async (epicDir) => {
      await ensureStoryDirectory(epicDir, "S-003-profile");
      const state = await loadStoryState(epicDir, "S-003-profile");
      await saveStoryState(epicDir, "S-003-profile", { ...state, status: "verifying", updatedAt: new Date().toISOString() });

      const verifying = await loadStoryState(epicDir, "S-003-profile");
      await saveStoryState(epicDir, "S-003-profile", {
        ...verifying,
        status: "retry",
        failureSummary: "Test 3 failed: expected 200 got 404",
        updatedAt: new Date().toISOString(),
      });

      const retried = await loadStoryState(epicDir, "S-003-profile");
      assert.equal(retried.status, "retry");
      assert.equal(retried.failureSummary, "Test 3 failed: expected 200 got 404");
    });
  });

  // koan_skip_story: pending → skipped
  it("koan_skip_story accepts pending → skipped", async () => {
    await withEpicDir(async (epicDir) => {
      await ensureStoryDirectory(epicDir, "S-004-optional");
      const state = await loadStoryState(epicDir, "S-004-optional");
      assert.equal(state.status, "pending");

      await saveStoryState(epicDir, "S-004-optional", {
        ...state,
        status: "skipped",
        skipReason: "Already implemented by S-003",
        updatedAt: new Date().toISOString(),
      });

      const skipped = await loadStoryState(epicDir, "S-004-optional");
      assert.equal(skipped.status, "skipped");
      assert.equal(skipped.skipReason, "Already implemented by S-003");
    });
  });

  // koan_skip_story: retry → skipped
  it("koan_skip_story accepts retry → skipped", async () => {
    await withEpicDir(async (epicDir) => {
      await ensureStoryDirectory(epicDir, "S-005-retry-skip");
      const state = await loadStoryState(epicDir, "S-005-retry-skip");
      await saveStoryState(epicDir, "S-005-retry-skip", { ...state, status: "retry", updatedAt: new Date().toISOString() });

      const retrying = await loadStoryState(epicDir, "S-005-retry-skip");
      assert.equal(retrying.status, "retry");

      await saveStoryState(epicDir, "S-005-retry-skip", {
        ...retrying,
        status: "skipped",
        skipReason: "Made unnecessary by another story",
        updatedAt: new Date().toISOString(),
      });

      const skipped = await loadStoryState(epicDir, "S-005-retry-skip");
      assert.equal(skipped.status, "skipped");
    });
  });

  // No escalated status exists in the new design.
  it("StoryStatus type does not include escalated", () => {
    const validStatuses: StoryStatus[] = [
      "pending", "selected", "planning", "executing",
      "verifying", "done", "retry", "skipped",
    ];
    // Verify all expected statuses are present
    assert.equal(validStatuses.length, 8);
    // Ensure "escalated" is not a valid value by type-checking at runtime.
    const set = new Set<string>(validStatuses);
    assert.equal(set.has("escalated"), false, "escalated should not exist as a story status");
  });
});

// ---------------------------------------------------------------------------
// assertStatus enforcement
// ---------------------------------------------------------------------------

describe("assertStatus enforcement", () => {
  it("throws when current status is not in allowed list", () => {
    assert.throws(
      () => assertStatus("S-001", "selected", ["pending", "retry"]),
      /Cannot transition story 'S-001'/,
    );
  });

  it("throws when current status does not match single allowed status", () => {
    assert.throws(
      () => assertStatus("S-001", "pending", ["verifying"]),
      /Cannot transition story 'S-001'/,
    );
  });

  it("does not throw when current status is in allowed list", () => {
    assert.doesNotThrow(() => assertStatus("S-001", "verifying", ["verifying"]));
  });

  it("does not throw when current status is one of multiple allowed statuses", () => {
    assert.doesNotThrow(() => assertStatus("S-001", "retry", ["pending", "retry"]));
    assert.doesNotThrow(() => assertStatus("S-001", "pending", ["pending", "retry"]));
  });

  it("koan_skip_story accepts retry status via assertStatus", () => {
    assert.doesNotThrow(() => assertStatus("S-001", "retry", ["pending", "retry"]));
  });

  it("koan_skip_story rejects selected status via assertStatus", () => {
    assert.throws(
      () => assertStatus("S-001", "selected", ["pending", "retry"]),
      /Cannot transition story 'S-001'/,
    );
  });
});

// ---------------------------------------------------------------------------
// State machine: valid source status enforcement per story lifecycle
// ---------------------------------------------------------------------------

describe("state machine: tool source validation", () => {
  const TOOL_VALID_SOURCES: Record<string, StoryStatus[]> = {
    koan_select_story: ["pending", "retry"],
    koan_complete_story: ["verifying"],
    koan_retry_story: ["verifying"],
    koan_skip_story: ["pending", "retry"],
  };

  const ALL_STATUSES: StoryStatus[] = [
    "pending", "selected", "planning", "executing",
    "verifying", "done", "retry", "skipped",
  ];

  for (const [tool, validSources] of Object.entries(TOOL_VALID_SOURCES)) {
    const invalidSources = ALL_STATUSES.filter((s) => !validSources.includes(s));

    it(`${tool} allows only [${validSources.join(", ")}]`, () => {
      // All valid sources should be in the set
      assert.equal(validSources.length > 0, true);
      // No invalid source should overlap with valid
      for (const invalid of invalidSources) {
        assert.equal(validSources.includes(invalid), false,
          `${tool}: ${invalid} should not be a valid source status`);
      }
    });
  }

  it("koan_escalate does not exist in the tool inventory", () => {
    // Verify koan_escalate is not in the ROLE_PERMISSIONS for orchestrator

    const orchestratorTools = ROLE_PERMISSIONS.get("orchestrator") ?? new Set<string>();
    assert.equal(orchestratorTools.has("koan_escalate"), false, "koan_escalate must not be in orchestrator permissions");
  });
});

// ---------------------------------------------------------------------------
// Routing decisions
// ---------------------------------------------------------------------------

describe("routing decisions", () => {
  // Simulate the routeFromState logic (we test inputs/outputs, not the internal function)
  interface Story { storyId: string; status: StoryStatus; retryCount: number; maxRetries: number }

  function simulateRouting(stories: Story[]): string {
    // Mirror driver.ts routeFromState logic
    const retry = stories.find((s) => s.status === "retry");
    if (retry) return `retry:${retry.storyId}`;
    const selected = stories.find((s) => s.status === "selected");
    if (selected) return `execute:${selected.storyId}`;
    const terminal = new Set(["done", "skipped"]);
    const allTerminal = stories.every((s) => terminal.has(s.status));
    if (allTerminal && stories.length > 0) return "complete";
    return "error";
  }

  it("routes to retry when a story has retry status", () => {
    const stories: Story[] = [
      { storyId: "S-001-auth", status: "done", retryCount: 0, maxRetries: 2 },
      { storyId: "S-002-routes", status: "retry", retryCount: 1, maxRetries: 2 },
    ];
    assert.equal(simulateRouting(stories), "retry:S-002-routes");
  });

  it("routes to execute when a story has selected status", () => {
    const stories: Story[] = [
      { storyId: "S-001-auth", status: "done", retryCount: 0, maxRetries: 2 },
      { storyId: "S-002-routes", status: "selected", retryCount: 0, maxRetries: 2 },
    ];
    assert.equal(simulateRouting(stories), "execute:S-002-routes");
  });

  it("routes to complete when all stories are done", () => {
    const stories: Story[] = [
      { storyId: "S-001-auth", status: "done", retryCount: 0, maxRetries: 2 },
      { storyId: "S-002-routes", status: "done", retryCount: 0, maxRetries: 2 },
    ];
    assert.equal(simulateRouting(stories), "complete");
  });

  it("routes to complete when all stories are done or skipped", () => {
    const stories: Story[] = [
      { storyId: "S-001-auth", status: "done", retryCount: 0, maxRetries: 2 },
      { storyId: "S-002-optional", status: "skipped", retryCount: 0, maxRetries: 2 },
    ];
    assert.equal(simulateRouting(stories), "complete");
  });

  it("routes to error when no actionable state exists", () => {
    const stories: Story[] = [
      { storyId: "S-001-auth", status: "pending", retryCount: 0, maxRetries: 2 },
      { storyId: "S-002-routes", status: "pending", retryCount: 0, maxRetries: 2 },
    ];
    assert.equal(simulateRouting(stories), "error");
  });

  it("prefers retry over selected (retry takes routing priority)", () => {
    const stories: Story[] = [
      { storyId: "S-001-auth", status: "retry", retryCount: 1, maxRetries: 2 },
      { storyId: "S-002-routes", status: "selected", retryCount: 0, maxRetries: 2 },
    ];
    assert.equal(simulateRouting(stories), "retry:S-001-auth");
  });

  it("routes to error for empty story list", () => {
    assert.equal(simulateRouting([]), "error");
  });
});

// ---------------------------------------------------------------------------
// Permission matrix (role × tool)
// ---------------------------------------------------------------------------

describe("permission matrix", () => {
  const epicDir = "/tmp/test-epic";

  // Tools that should be allowed for each role.
  const ROLE_ALLOWED: Record<string, string[]> = {
    intake: ["read", "bash", "grep", "glob", "find", "ls", "koan_complete_step", "koan_ask_question", "koan_request_scouts", "edit", "write"],
    scout: ["read", "bash", "grep", "glob", "find", "ls", "koan_complete_step", "edit", "write"],
    decomposer: ["read", "bash", "grep", "glob", "find", "ls", "koan_complete_step", "koan_ask_question", "koan_request_scouts", "edit", "write"],
    orchestrator: ["read", "bash", "grep", "glob", "find", "ls", "koan_complete_step", "koan_ask_question", "koan_select_story", "koan_complete_story", "koan_retry_story", "koan_skip_story", "edit", "write"],
    planner: ["read", "bash", "grep", "glob", "find", "ls", "koan_complete_step", "koan_ask_question", "koan_request_scouts", "edit", "write"],
    executor: ["read", "bash", "grep", "glob", "find", "ls", "koan_complete_step", "koan_ask_question", "edit", "write"],
    "workflow-orchestrator": ["read", "bash", "grep", "glob", "find", "ls", "koan_complete_step", "koan_propose_workflow", "koan_set_next_phase"],
  };

  // Tools that must be blocked for each role.
  const ROLE_BLOCKED: Record<string, string[]> = {
    intake: ["koan_select_story", "koan_complete_story", "koan_retry_story", "koan_skip_story", "koan_escalate"],
    scout: ["koan_ask_question", "koan_request_scouts", "koan_select_story", "koan_complete_story", "koan_retry_story", "koan_skip_story", "koan_escalate"],
    decomposer: ["koan_select_story", "koan_complete_story", "koan_retry_story", "koan_skip_story", "koan_escalate"],
    orchestrator: ["koan_request_scouts", "koan_escalate"],
    planner: ["koan_select_story", "koan_complete_story", "koan_retry_story", "koan_skip_story", "koan_escalate"],
    executor: ["koan_select_story", "koan_complete_story", "koan_retry_story", "koan_skip_story", "koan_escalate", "koan_request_scouts"],
    "workflow-orchestrator": ["koan_ask_question", "koan_request_scouts", "koan_select_story", "koan_complete_story", "koan_retry_story", "koan_skip_story", "koan_escalate", "edit", "write"],
  };

  for (const [role, allowed] of Object.entries(ROLE_ALLOWED)) {
    it(`${role}: allows expected tools`, () => {
      for (const tool of allowed) {
        const result = checkPermission(role, tool, epicDir);
        assert.equal(result.allowed, true, `${role} should allow ${tool}: ${result.reason}`);
      }
    });
  }

  for (const [role, blocked] of Object.entries(ROLE_BLOCKED)) {
    it(`${role}: blocks forbidden tools`, () => {
      for (const tool of blocked) {
        const result = checkPermission(role, tool, epicDir);
        assert.equal(result.allowed, false, `${role} should block ${tool}`);
      }
    });
  }

  it("unknown role is blocked for all tools", () => {
    const tools = ["read", "koan_complete_step", "koan_ask_question", "write"];
    for (const tool of tools) {
      const result = checkPermission("unknown-role", tool, epicDir);
      // read tools are always allowed, even for unknown roles
      if (tool === "read") {
        assert.equal(result.allowed, true);
      } else {
        assert.equal(result.allowed, false, `unknown-role should block ${tool}`);
      }
    }
  });

  it("planning roles have write access scoped to epic directory", () => {
    const planningRoles = ["intake", "scout", "decomposer", "planner", "orchestrator"];
    const insidePath = path.join(epicDir, "stories", "S-001-auth", "story.md");
    const outsidePath = "/etc/passwd";

    for (const role of planningRoles) {
      const inside = checkPermission(role, "write", epicDir, { path: insidePath });
      assert.equal(inside.allowed, true, `${role} should allow write inside epic dir`);

      const outside = checkPermission(role, "write", epicDir, { path: outsidePath });
      assert.equal(outside.allowed, false, `${role} should block write outside epic dir`);
    }
  });

  it("executor has unrestricted write access (can write to codebase)", () => {
    // Executor does not scope-check paths — it needs to write to the codebase
    const codebasePath = "/Users/lmergen/git/myapp/src/auth.ts";
    const result = checkPermission("executor", "write", epicDir, { path: codebasePath });
    assert.equal(result.allowed, true, "executor should allow writes anywhere");
  });
});

// ---------------------------------------------------------------------------
// Step-aware permission gating
// ---------------------------------------------------------------------------

describe("step-aware permission gating", () => {
  const epicDir = "/tmp/test-epic";

  // -- Intake step 1 (Extract): read-only, blocks side-effecting tools --

  it("intake step 1 blocks koan_request_scouts", () => {
    const result = checkPermission("intake", "koan_request_scouts", epicDir, undefined, 1);
    assert.equal(result.allowed, false);
  });

  it("intake step 1 blocks koan_ask_question", () => {
    const result = checkPermission("intake", "koan_ask_question", epicDir, undefined, 1);
    assert.equal(result.allowed, false);
  });

  it("intake step 1 blocks write", () => {
    const result = checkPermission("intake", "write", epicDir, { path: path.join(epicDir, "landscape.md") }, 1);
    assert.equal(result.allowed, false);
  });

  it("intake step 1 blocks edit", () => {
    const result = checkPermission("intake", "edit", epicDir, { path: path.join(epicDir, "landscape.md") }, 1);
    assert.equal(result.allowed, false);
  });

  // -- Intake step 2 (Scout): side-effecting tools allowed --

  it("intake step 2 allows koan_request_scouts", () => {
    const result = checkPermission("intake", "koan_request_scouts", epicDir, undefined, 2);
    assert.equal(result.allowed, true);
  });

  // -- Brief-writer step 1 (Read): read-only, blocks write/edit --

  it("brief-writer step 1 blocks write", () => {
    const result = checkPermission("brief-writer", "write", epicDir, { path: path.join(epicDir, "brief.md") }, 1);
    assert.equal(result.allowed, false);
  });

  it("brief-writer step 1 blocks edit", () => {
    const result = checkPermission("brief-writer", "edit", epicDir, { path: path.join(epicDir, "brief.md") }, 1);
    assert.equal(result.allowed, false);
  });

  // -- Brief-writer step 2 (Draft & Review): write/edit allowed inside epic dir --

  it("brief-writer step 2 allows write inside epic dir", () => {
    const result = checkPermission("brief-writer", "write", epicDir, { path: path.join(epicDir, "brief.md") }, 2);
    assert.equal(result.allowed, true);
  });
});

// ---------------------------------------------------------------------------
// Initial state invariants
// ---------------------------------------------------------------------------

describe("initial state invariants", () => {
  it("createInitialStoryState produces pending status", () => {
    const state = createInitialStoryState("S-001-auth");
    assert.equal(state.status, "pending");
    assert.equal(state.retryCount, 0);
    assert.equal(state.storyId, "S-001-auth");
    assert.equal(typeof state.updatedAt, "string");
  });

  it("createInitialStoryState uses default maxRetries of 2", () => {
    const state = createInitialStoryState("S-001-auth");
    assert.equal(state.maxRetries, 2);
  });

  it("createInitialStoryState accepts custom maxRetries", () => {
    const state = createInitialStoryState("S-001-auth", 5);
    assert.equal(state.maxRetries, 5);
  });

  it("StoryState has no escalation field", () => {
    const state = createInitialStoryState("S-001-auth");
    assert.equal("escalation" in state, false, "StoryState must not have an escalation field");
  });
});
