import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { pool } from "../src/planner/lib/pool.js";

describe("pool", () => {
  it("returns empty failed when all workers succeed", async () => {
    const result = await pool(
      ["a", "b", "c"],
      2,
      async () => true,
    );

    assert.equal(result.total, 3);
    assert.equal(result.completed, 3);
    assert.deepEqual(result.failed, []);
  });

  it("collects IDs of workers that return false", async () => {
    const failSet = new Set(["b", "d"]);
    const result = await pool(
      ["a", "b", "c", "d"],
      2,
      async (id) => !failSet.has(id),
    );

    assert.equal(result.total, 4);
    assert.equal(result.completed, 4);
    assert.deepEqual(result.failed.sort(), ["b", "d"]);
  });

  it("completes all items regardless of failures", async () => {
    const result = await pool(
      ["a", "b", "c"],
      1,
      async () => false,
    );

    assert.equal(result.total, 3);
    assert.equal(result.completed, 3);
    assert.equal(result.failed.length, 3);
  });

  it("propagates worker exceptions without catching", async () => {
    await assert.rejects(
      () => pool(
        ["a", "b"],
        2,
        async (id) => {
          if (id === "b") throw new Error("boom");
          return true;
        },
      ),
      { message: "boom" },
    );
  });

  it("invokes onProgress callback", async () => {
    const updates: Array<{ done: number; total: number }> = [];
    await pool(
      ["a", "b"],
      1,
      async () => true,
      (p) => updates.push({ done: p.done, total: p.total }),
    );

    assert.ok(updates.length > 0);
    const last = updates[updates.length - 1];
    assert.equal(last.done, 2);
    assert.equal(last.total, 2);
  });
});
