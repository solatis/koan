/**
 * explorationAdapter — store→view-model adapter for exploration aggregate
 * and single-op rendering.
 *
 * Maps the store's `ExplorationChild[]` (the six exploration families) to the
 * `ExplorationOp[]` view model consumed by `groupExplorationOps` (aggregate
 * path → ToolAggregateCard) and by `renderEntryBody`'s single-op cases
 * (single-op path → ToolCallRow family variant). Owning all string formatting
 * here keeps the two rendering paths from drifting against the single
 * design-spec metric table.
 *
 * Formatting contract: docs/design-system.md — Molecules → ToolLogRow
 * "Metric formats by family". Running verbs (with ellipsis) replace the
 * completed metric while a child is in flight, per the ToolLogRow running
 * state spec. `metricTone` selects the metric styling class (`fail` →
 * --status-failed, `zero` → italic muted).
 *
 * Spec: docs/design-system.md — Organisms → ToolAggregateCard
 * ("Rendering rule (stream level)") and Molecules → ToolLogRow.
 */

import type { ExplorationChild, ToolAggregateEntry } from '../../store/index'
import type { ExplorationOp } from './toolAggregateGrouping'

/**
 * Format a byte count as a kilobyte string, e.g. 9114 → "8.9 KB".
 *
 * Intentional duplication of the private `formatKb` in
 * `toolAggregateGrouping.ts`: that one is for rollup meta lines (the grouping
 * utility is store-free and formats its own sums); this one is for per-op
 * metrics here in the adapter. The two should stay byte-for-byte identical.
 */
function formatKb(bytes: number): string {
  return `${(bytes / 1024).toFixed(1)} KB`
}

/**
 * Return the first line of a command string (split on `\n`).
 *
 * Intentional duplication of the private `firstLine` in
 * `ToolCommandText.tsx`: the adapter should not depend on atom internals,
 * and the running-label needs only the first line of a bash command.
 */
function firstLine(command: string): string {
  const i = command.indexOf('\n')
  return i === -1 ? command : command.slice(0, i)
}

/**
 * Extract the host from a URL (scheme and path stripped).
 *
 * Intentional duplication of the private `splitUrl` in
 * `ToolCommandText.tsx`: the adapter should not depend on atom internals,
 * and the running-label needs only the host of a fetched URL.
 */
function hostname(url: string): string {
  const stripped = url.replace(/^[a-z][a-z0-9+.-]*:\/\//i, '')
  const i = stripped.indexOf('/')
  return i === -1 ? stripped : stripped.slice(0, i)
}

/** In-progress verbs (with ellipsis) shown as the metric for an in-flight
 *  op, per the ToolLogRow running-state spec. */
const RUNNING_VERB: Record<ExplorationChild['type'], string> = {
  tool_read: 'reading…',
  tool_grep: 'grepping…',
  tool_glob: 'globbing…',
  tool_bash: 'running…',
  tool_web_search: 'searching…',
  tool_web_fetch: 'fetching…',
}

/**
 * Map an `ExplorationChild` store entry to an `ExplorationOp` view model.
 *
 * Owns the per-family metric string, `metricTone`, read `range`, structured
 * `stats` passthrough (never parsed back out of the metric string), and the
 * running-verb override while the child is in flight. The same output feeds
 * both the aggregate card (via `groupExplorationOps`) and the single-op
 * `ToolCallRow` family variant.
 */
export function toExplorationOp(child: ExplorationChild, seq: number): ExplorationOp {
  const status: 'done' | 'running' | 'error' = child.inFlight ? 'running' : 'done'
  let op: ExplorationOp
  switch (child.type) {
    case 'tool_read': {
      const range = child.limit != null && child.limit > 0
        ? `${child.offset + 1}–${child.offset + child.limit}`
        : undefined
      // Spec: "{n} lines · {kb} KB". When bytesRead is null (defensive —
      // beyond the spec, which only defines the combined form) fall back to
      // "{n} lines" so a partial read still shows a metric.
      const metric = child.linesRead != null
        ? child.bytesRead != null
          ? `${child.linesRead} lines · ${formatKb(child.bytesRead)}`
          : `${child.linesRead} lines`
        : undefined
      op = {
        family: 'read',
        command: { path: child.file, range },
        metric,
        status,
        seq,
        stats: child.linesRead != null ? { lines: child.linesRead, bytes: child.bytesRead ?? 0 } : undefined,
      }
      break
    }
    case 'tool_grep': {
      const zero = child.matches === 0
      // Spec: "{m} matches · {l} lines · {f} files". Zero matches render
      // "0 matches" only (italic muted via metricTone 'zero') — not the
      // three-field form, per the design spec.
      const metric = child.matches != null
        ? zero
          ? '0 matches'
          : `${child.matches} matches · ${child.matchedLines ?? 0} lines · ${child.filesMatched ?? 0} files`
        : undefined
      op = {
        family: 'grep',
        command: { pattern: child.pattern },
        metric,
        status,
        metricTone: zero ? 'zero' : 'default',
        seq,
        stats: child.matches != null
          ? { matches: child.matches, matchedLines: child.matchedLines ?? 0 }
          : undefined,
      }
      break
    }
    case 'tool_glob': {
      op = {
        family: 'glob',
        command: { pattern: child.pattern },
        metric: child.matches != null ? `${child.matches} files` : undefined,
        status,
        seq,
        stats: child.matches != null ? { files: child.matches } : undefined,
      }
      break
    }
    case 'tool_bash': {
      const fail = child.exitCode != null && child.exitCode !== 0
      op = {
        family: 'bash',
        command: { command: child.command },
        metric: child.exitCode != null
          ? `exit ${child.exitCode}${child.outputLines != null ? ` · ${child.outputLines} lines` : ''}`
          : undefined,
        status: fail ? 'error' : status,
        metricTone: fail ? 'fail' : 'default',
        seq,
      }
      break
    }
    case 'tool_web_search': {
      op = {
        family: 'web_search',
        command: { query: child.query },
        metric: child.resultCount != null ? `${child.resultCount} results` : undefined,
        status,
        seq,
        stats: child.resultCount != null ? { results: child.resultCount } : undefined,
      }
      break
    }
    case 'tool_web_fetch': {
      op = {
        family: 'web_fetch',
        command: { url: child.url },
        // Spec: "{kb} KB". Use the shared formatKb helper (parity with the
        // grouping utility's rollup formatting) instead of inlining the
        // division.
        metric: child.contentSizeBytes != null ? formatKb(child.contentSizeBytes) : undefined,
        status,
        seq,
        stats: child.contentSizeBytes != null ? { bytes: child.contentSizeBytes } : undefined,
      }
      break
    }
  }
  // While in flight, the metric shows the running verb (with ellipsis) in
  // place of the completed figure, per the ToolLogRow running-state spec.
  if (child.inFlight) op.metric = RUNNING_VERB[child.type]
  // A validation-failed child (tool_failed fold) never ran: force the error
  // status and fail-toned metric regardless of family.
  if (child.failed) {
    op.status = 'error'
    op.metric = 'invalid arguments'
    op.metricTone = 'fail'
  }
  return op
}

/**
 * Derive the card-header running label for a single in-flight child.
 *
 * Format: verb + short argument. The argument is the first meaningful field —
 * `file` basename for read, `pattern` for grep/glob, first line of `command`
 * for bash, `query` for web_search, host from `url` for web_fetch.
 */
export function runningLabelFor(child: ExplorationChild): string {
  switch (child.type) {
    case 'tool_read': return `reading ${child.file.split('/').pop() || child.file}`
    case 'tool_grep': return `grepping ${child.pattern}`
    case 'tool_glob': return `globbing ${child.pattern}`
    case 'tool_bash': return `running ${firstLine(child.command)}`
    case 'tool_web_search': return `searching ${child.query}`
    case 'tool_web_fetch': return `fetching ${hostname(child.url)}`
  }
}

/** Find the first in-flight child in a chronological run, if any. */
export function findRunningChild(children: ExplorationChild[]): ExplorationChild | undefined {
  return children.find(c => c.inFlight)
}

/**
 * Compute the aggregate's elapsed duration in milliseconds.
 *
 * While a child is in flight, elapsed ticks from the aggregate's first-child
 * `startedAtMs` to `nowMs`. Once all children complete, elapsed freezes at
 * the span from `startedAtMs` to the latest `completedAtMs`. The live-ticking
 * variant (for the card header) is `useElapsed` in the React component; this
 * pure function is kept for callers that need a snapshot value.
 */
export function aggregateElapsedMs(agg: ToolAggregateEntry, nowMs: number): number {
  const running = findRunningChild(agg.children)
  if (running) {
    return Math.max(0, nowMs - agg.startedAtMs)
  }
  let latest = agg.startedAtMs
  for (const c of agg.children) {
    if (c.completedAtMs != null && c.completedAtMs > latest) latest = c.completedAtMs
  }
  return Math.max(0, latest - agg.startedAtMs)
}