// Severity escalation policy for QR fix iterations.
//
// Progressive de-escalation narrows what blocks as iterations increase.
// COULD items (style, cosmetic) do not block indefinitely: after 2 fix
// attempts, only structural issues (MUST, SHOULD) block; after 3, only
// knowledge-loss risks (MUST) block.
//
// A hard cutoff ("after N attempts, ignore all failures") would let MUST
// failures through. De-escalation by tier preserves the invariant that
// MUST items always block, while preventing COULD style nits from causing
// indefinite retries.

import type { QRItem, QRSeverity } from "./types.js";

export const MAX_FIX_ITERATIONS = 5;

// Returns the set of severities that block the plan at the given iteration.
// Iterations 1-2: all severities block. Iteration 3: MUST+SHOULD. 4+: MUST only.
export function blockingSeverities(iteration: number): ReadonlySet<QRSeverity> {
  if (iteration <= 2) return new Set<QRSeverity>(["MUST", "SHOULD", "COULD"]);
  if (iteration === 3) return new Set<QRSeverity>(["MUST", "SHOULD"]);
  return new Set<QRSeverity>(["MUST"]);
}

// Returns the subset of items that are FAIL and have a blocking severity
// at the given iteration.
export function blockingFailures(
  items: ReadonlyArray<QRItem>,
  iteration: number,
): QRItem[] {
  const blocking = blockingSeverities(iteration);
  return items.filter((i) => i.status === "FAIL" && blocking.has(i.severity));
}

// Returns true when no blocking failures remain at this iteration.
export function qrPassesAtIteration(
  items: ReadonlyArray<QRItem>,
  iteration: number,
): boolean {
  return blockingFailures(items, iteration).length === 0;
}
