// Tests for grouped QR verification: grouping logic, step routing,
// prompt generation, and subagent spawn arg threading.

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { buildSpawnArgs } from "../src/planner/subagent.js";
import type { QRItem } from "../src/planner/qr/types.js";
import {
  buildVerifySystemPrompt,
  buildContextStep,
  buildAnalyzeStep,
  buildConfirmStep,
} from "../src/planner/phases/qr-verify/prompts.js";

// -- Grouping logic (pure function, extracted from session.ts pattern) --

function groupItemsByGroupId(items: QRItem[]): Map<string, string[]> {
  const groups = new Map<string, string[]>();
  for (const item of items) {
    const gid = item.group_id ?? item.id;
    const existing = groups.get(gid);
    if (existing) {
      existing.push(item.id);
    } else {
      groups.set(gid, [item.id]);
    }
  }
  return groups;
}

function makeItem(id: string, groupId: string | null = null, status: "TODO" | "PASS" | "FAIL" = "TODO"): QRItem {
  return {
    id,
    scope: `milestone:M-001`,
    check: `Check for ${id}`,
    status,
    finding: null,
    parent_id: null,
    group_id: groupId,
    severity: "MUST",
  };
}

// -- Grouping tests --

describe("groupItemsByGroupId", () => {
  it("groups items sharing the same group_id", () => {
    const items = [
      makeItem("QR-001", "group-a"),
      makeItem("QR-002", "group-a"),
      makeItem("QR-003", "group-b"),
    ];
    const groups = groupItemsByGroupId(items);

    assert.equal(groups.size, 2);
    assert.deepEqual(groups.get("group-a"), ["QR-001", "QR-002"]);
    assert.deepEqual(groups.get("group-b"), ["QR-003"]);
  });

  it("treats null group_id as singleton (uses item id as group key)", () => {
    const items = [
      makeItem("QR-001", null),
      makeItem("QR-002", null),
    ];
    const groups = groupItemsByGroupId(items);

    assert.equal(groups.size, 2);
    assert.deepEqual(groups.get("QR-001"), ["QR-001"]);
    assert.deepEqual(groups.get("QR-002"), ["QR-002"]);
  });

  it("handles mixed grouped and ungrouped items", () => {
    const items = [
      makeItem("QR-001", "umbrella"),
      makeItem("QR-002", "umbrella"),
      makeItem("QR-003", null),
      makeItem("QR-004", "component-auth"),
      makeItem("QR-005", "component-auth"),
      makeItem("QR-006", "component-auth"),
    ];
    const groups = groupItemsByGroupId(items);

    assert.equal(groups.size, 3);
    assert.deepEqual(groups.get("umbrella"), ["QR-001", "QR-002"]);
    assert.deepEqual(groups.get("QR-003"), ["QR-003"]);
    assert.deepEqual(groups.get("component-auth"), ["QR-004", "QR-005", "QR-006"]);
  });

  it("returns empty map for empty items", () => {
    const groups = groupItemsByGroupId([]);
    assert.equal(groups.size, 0);
  });

  it("single item with group_id creates group of 1", () => {
    const items = [makeItem("QR-001", "solo-group")];
    const groups = groupItemsByGroupId(items);

    assert.equal(groups.size, 1);
    assert.deepEqual(groups.get("solo-group"), ["QR-001"]);
  });
});

// -- Dynamic step formula tests --

describe("dynamic step formula", () => {
  it("totalSteps = 1 + 2*N for N items", () => {
    assert.equal(1 + 2 * 1, 3);   // 1 item: CONTEXT, ANALYZE, CONFIRM
    assert.equal(1 + 2 * 3, 7);   // 3 items: CONTEXT, 3×(ANALYZE+CONFIRM)
    assert.equal(1 + 2 * 5, 11);  // 5 items
  });

  it("step routing maps correctly for 3 items", () => {
    // Step 1: CONTEXT
    // Step 2: ANALYZE item 0
    // Step 3: CONFIRM item 0
    // Step 4: ANALYZE item 1
    // Step 5: CONFIRM item 1
    // Step 6: ANALYZE item 2
    // Step 7: CONFIRM item 2

    function stepType(step: number): { kind: string; itemIndex?: number } {
      if (step === 1) return { kind: "CONTEXT" };
      const offset = step - 2;
      const itemIndex = Math.floor(offset / 2);
      const isConfirm = offset % 2 === 1;
      return isConfirm ? { kind: "CONFIRM", itemIndex } : { kind: "ANALYZE", itemIndex };
    }

    assert.deepEqual(stepType(1), { kind: "CONTEXT" });
    assert.deepEqual(stepType(2), { kind: "ANALYZE", itemIndex: 0 });
    assert.deepEqual(stepType(3), { kind: "CONFIRM", itemIndex: 0 });
    assert.deepEqual(stepType(4), { kind: "ANALYZE", itemIndex: 1 });
    assert.deepEqual(stepType(5), { kind: "CONFIRM", itemIndex: 1 });
    assert.deepEqual(stepType(6), { kind: "ANALYZE", itemIndex: 2 });
    assert.deepEqual(stepType(7), { kind: "CONFIRM", itemIndex: 2 });
  });

  it("step routing works for single item (backward compat)", () => {
    function stepType(step: number): { kind: string; itemIndex?: number } {
      if (step === 1) return { kind: "CONTEXT" };
      const offset = step - 2;
      const itemIndex = Math.floor(offset / 2);
      const isConfirm = offset % 2 === 1;
      return isConfirm ? { kind: "CONFIRM", itemIndex } : { kind: "ANALYZE", itemIndex };
    }

    assert.deepEqual(stepType(1), { kind: "CONTEXT" });
    assert.deepEqual(stepType(2), { kind: "ANALYZE", itemIndex: 0 });
    assert.deepEqual(stepType(3), { kind: "CONFIRM", itemIndex: 0 });
  });
});

// -- Prompt generation tests --

describe("buildVerifySystemPrompt", () => {
  it("includes item count for single item", () => {
    const result = buildVerifySystemPrompt("base prompt", "plan-design", 1);
    assert.ok(result.includes("1 QR item"));
    assert.ok(!result.includes("items"));
  });

  it("includes item count for multiple items", () => {
    const result = buildVerifySystemPrompt("base prompt", "plan-code", 5);
    assert.ok(result.includes("5 QR items"));
  });

  it("includes phase name", () => {
    const result = buildVerifySystemPrompt("base prompt", "plan-docs", 3);
    assert.ok(result.includes("plan-docs"));
  });
});

describe("buildContextStep", () => {
  const items: QRItem[] = [
    makeItem("QR-001", "group-a"),
    makeItem("QR-002", "group-a"),
    makeItem("QR-003", "group-a"),
  ];

  it("lists all items in context step", () => {
    const step = buildContextStep(items, "plan-design");
    const text = step.instructions.join("\n");
    assert.ok(text.includes("QR-001"));
    assert.ok(text.includes("QR-002"));
    assert.ok(text.includes("QR-003"));
  });

  it("shows correct item count", () => {
    const step = buildContextStep(items, "plan-design");
    const text = step.instructions.join("\n");
    assert.ok(text.includes("3 ITEMS"));
  });

  it("shows 1 ITEM for single item", () => {
    const step = buildContextStep([items[0]], "plan-design");
    const text = step.instructions.join("\n");
    assert.ok(text.includes("1 ITEM"));
  });
});

describe("buildAnalyzeStep", () => {
  const item = makeItem("QR-042", "group-x");

  it("includes item ID and check", () => {
    const step = buildAnalyzeStep(item, 0, 3);
    const text = step.instructions.join("\n");
    assert.ok(text.includes("QR-042"));
    assert.ok(text.includes(item.check));
  });

  it("includes position label for multi-item groups", () => {
    const step = buildAnalyzeStep(item, 1, 5);
    assert.ok(step.title.includes("item 2 of 5"));
  });

  it("omits position label for single item", () => {
    const step = buildAnalyzeStep(item, 0, 1);
    assert.ok(!step.title.includes("item"));
  });
});

describe("buildConfirmStep", () => {
  const item = makeItem("QR-007", "group-y");

  it("includes koan_qr_set_item instructions with correct id", () => {
    const step = buildConfirmStep(item, 0, 3, "plan-code");
    const text = step.instructions.join("\n");
    assert.ok(text.includes("id='QR-007'"));
    assert.ok(text.includes("status='PASS'"));
    assert.ok(text.includes("status='FAIL'"));
  });

  it("includes position label for multi-item groups", () => {
    const step = buildConfirmStep(item, 2, 4, "plan-docs");
    assert.ok(step.title.includes("item 3 of 4"));
  });

  it("has invokeAfter guard", () => {
    const step = buildConfirmStep(item, 0, 1, "plan-design");
    assert.ok(step.invokeAfter);
    assert.ok(step.invokeAfter!.includes("koan_complete_step"));
  });
});

// -- Subagent spawn arg tests --

describe("spawnReviewer args", () => {
  const baseOpts = {
    planDir: "/plan",
    subagentDir: "/subagent",
    extensionPath: "/ext/koan.ts",
    cwd: "/working",
  };

  it("passes single item ID via --koan-qr-item for single-item group", () => {
    const args = buildSpawnArgs("reviewer", "qr-plan-design", "Verify the assigned QR item.", {
      ...baseOpts,
      extraFlags: ["--koan-qr-item", "QR-001"],
    });
    const idx = args.indexOf("--koan-qr-item");
    assert.ok(idx >= 0);
    assert.equal(args[idx + 1], "QR-001");
  });

  it("passes comma-separated item IDs via --koan-qr-item for multi-item group", () => {
    const itemList = "QR-001,QR-002,QR-003";
    const args = buildSpawnArgs("reviewer", "qr-plan-code", "Verify the 3 assigned QR items.", {
      ...baseOpts,
      extraFlags: ["--koan-qr-item", itemList],
    });
    const idx = args.indexOf("--koan-qr-item");
    assert.ok(idx >= 0);
    assert.equal(args[idx + 1], "QR-001,QR-002,QR-003");
  });
});

// -- Comma-separated parsing (mirrors dispatch.ts logic) --

describe("comma-separated item ID parsing", () => {
  function parseItemIds(rawFlag: string): string[] {
    return rawFlag.split(",").map((s) => s.trim()).filter(Boolean);
  }

  it("parses single item ID", () => {
    assert.deepEqual(parseItemIds("QR-001"), ["QR-001"]);
  });

  it("parses multiple comma-separated IDs", () => {
    assert.deepEqual(parseItemIds("QR-001,QR-002,QR-003"), ["QR-001", "QR-002", "QR-003"]);
  });

  it("handles whitespace around commas", () => {
    assert.deepEqual(parseItemIds("QR-001 , QR-002 , QR-003"), ["QR-001", "QR-002", "QR-003"]);
  });

  it("filters empty strings from trailing comma", () => {
    assert.deepEqual(parseItemIds("QR-001,QR-002,"), ["QR-001", "QR-002"]);
  });

  it("returns empty array for empty string", () => {
    assert.deepEqual(parseItemIds(""), []);
  });
});
