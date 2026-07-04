/**
 * toolAggregateGrouping — pure grouping utility for the family-grouped
 * ToolAggregateCard organism.
 *
 * Folds a chronological run of exploration operations into FamilyGroups:
 * one group per family in first-occurrence order, chronological order
 * preserved within each group, rollup meta lines computed from the ops'
 * structured `stats` (never parsed from metric strings). The group
 * containing a running op is marked active.
 *
 * Deliberately store-free: operates on the view-model types below, not
82257f97§ * on the store's ExplorationChild union (which carries all six families).
 *
 * Spec: docs/design-system.md — Organisms → ToolAggregateCard.
 */

import type { ExplorationFamily, ToolCommandTextProps } from '../atoms/ToolCommandText'

export interface ExplorationOp {
  family: ExplorationFamily
  command: Omit<ToolCommandTextProps, 'family' | 'running' | 'error'>
  metric?: string
  status: 'done' | 'running' | 'error'
  metricTone?: 'default' | 'fail' | 'zero'
  /** Chronological index within the aggregate. */
  seq: number
  /** Structured amounts for rollups. Running ops contribute to opCount
   *  but their stats are excluded from sums. */
  stats?: {
    lines?: number
    bytes?: number
    matches?: number
    matchedLines?: number
    files?: number
    results?: number
  }
}

export interface FamilyGroup {
  family: ExplorationFamily
  /** Chronological within the family. */
  ops: ExplorationOp[]
  opCount: number
  /** Rollup lines for the ToolStatBlock (suppressed there for
   *  single-op groups). */
  metaLines: string[]
  failedCount: number
  /** True when this group owns the running op. */
  active: boolean
}

function formatKb(bytes: number): string {
  return `${(bytes / 1024).toFixed(1)} KB`
}

/** Sum a stats field across ops that have completed (running ops are
 *  excluded from all rollup sums). */
function sumStat(ops: ExplorationOp[], field: keyof NonNullable<ExplorationOp['stats']>): number {
  return ops.reduce(
    (total, op) => (op.status === 'running' ? total : total + (op.stats?.[field] ?? 0)),
    0
  )
}

/** Distinct read paths among completed (done) ops — a failed read
 *  produced no file content, a running read has not produced one yet. */
function distinctFiles(ops: ExplorationOp[]): number {
  const paths = new Set(
    ops.filter(op => op.status === 'done' && op.command.path != null).map(op => op.command.path)
  )
  return paths.size
}

function metaLines(family: ExplorationFamily, ops: ExplorationOp[]): string[] {
  switch (family) {
    case 'read':
      return [
        `${sumStat(ops, 'lines')} lines · ${formatKb(sumStat(ops, 'bytes'))}`,
        `${distinctFiles(ops)} files`,
      ]
    case 'grep':
      // Never file counts: summing per-op file counts double-counts
      // files matched by multiple patterns (see design rationale).
      return [`${sumStat(ops, 'matches')} matches · ${sumStat(ops, 'matchedLines')} lines`]
    case 'glob':
      return [`${sumStat(ops, 'files')} files`]
    case 'bash':
      return [] // failures surface via failedCount
    case 'web_search':
      return [`${sumStat(ops, 'results')} results`]
    case 'web_fetch':
      return [formatKb(sumStat(ops, 'bytes'))]
  }
}

function failedCount(ops: ExplorationOp[]): number {
  return ops.filter(
    op => op.status === 'error' || (op.family === 'bash' && op.metricTone === 'fail')
  ).length
}

export function groupExplorationOps(ops: ExplorationOp[]): FamilyGroup[] {
  const byFamily = new Map<ExplorationFamily, ExplorationOp[]>()
  for (const op of [...ops].sort((a, b) => a.seq - b.seq)) {
    const group = byFamily.get(op.family)
    if (group) {
      group.push(op)
    } else {
      byFamily.set(op.family, [op]) // Map preserves first-occurrence order
    }
  }
  return [...byFamily.entries()].map(([family, familyOps]) => ({
    family,
    ops: familyOps,
    opCount: familyOps.length,
    metaLines: metaLines(family, familyOps),
    failedCount: failedCount(familyOps),
    active: familyOps.some(op => op.status === 'running'),
  }))
}
