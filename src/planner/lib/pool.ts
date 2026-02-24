// Bounded-parallel subagent pool using an in-process semaphore.
// Runs all items to completion regardless of failures; callers inspect PoolResult.
// Timeout logic belongs in the worker closure, not here.

import type { SubagentResult } from "../subagent.js";

// -- Types --

export interface PoolResult {
  total: number;
  completed: number;
  failed: string[];
}

// -- Constants --

export const DEFAULT_REVIEWER_TIMEOUT_MS = 10 * 60 * 1000;

// -- Private helpers --

class Semaphore {
  private queue: Array<() => void> = [];
  private count: number;

  constructor(limit: number) {
    this.count = limit;
  }

  acquire(): Promise<void> {
    if (this.count > 0) {
      this.count--;
      return Promise.resolve();
    }
    return new Promise((resolve) => this.queue.push(resolve));
  }

  release(): void {
    const next = this.queue.shift();
    if (next) next();
    else this.count++;
  }
}

// -- Exports --

export async function pool(
  itemIds: string[],
  limit: number,
  worker: (itemId: string) => Promise<SubagentResult>,
  onProgress?: (done: number, total: number) => void,
): Promise<PoolResult> {
  const sem = new Semaphore(limit);
  const total = itemIds.length;
  const failed: string[] = [];
  let completed = 0;

  await Promise.all(
    itemIds.map(async (id) => {
      await sem.acquire();
      try {
        const r = await worker(id);
        if (r.exitCode !== 0) {
          failed.push(id);
        }
      } finally {
        completed++;
        onProgress?.(completed, total);
        sem.release();
      }
    }),
  );

  return { total, completed, failed };
}
