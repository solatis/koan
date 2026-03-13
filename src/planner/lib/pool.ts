// Bounded-parallel subagent pool using an in-process semaphore.
// Runs all items to completion regardless of individual failures.
// Timeout logic belongs in the worker closure, not here.

import type { SubagentResult } from "../subagent.js";

// -- Types --

export interface PoolResult {
  total: number;
  completed: number;
  failed: string[];
}

export interface PoolProgress {
  done: number;
  total: number;
  active: number;
  queued: number;
}

// -- Private helpers --

class Semaphore {
  private readonly queue: Array<() => void> = [];
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
  onProgress?: (progress: PoolProgress) => void,
): Promise<PoolResult> {
  const sem = new Semaphore(limit);
  const total = itemIds.length;
  const failed: string[] = [];
  let completed = 0;
  let running = 0;

  const emit = () => {
    onProgress?.({
      done: completed,
      total,
      active: running,
      queued: Math.max(0, total - completed - running),
    });
  };

  emit();

  await Promise.all(
    itemIds.map(async (id) => {
      await sem.acquire();
      running++;
      emit();

      try {
        const result = await worker(id);
        if (result.exitCode !== 0) {
          failed.push(id);
        }
      } finally {
        running = Math.max(0, running - 1);
        completed++;
        emit();
        sem.release();
      }
    }),
  );

  return { total, completed, failed };
}
