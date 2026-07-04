/**
 * ToolStatBlock — the navy stat cell for one family group inside the
 * ToolAggregateCard organism.
 *
 * Renders on --color-navy; all text uses the on-dark palette. The header
 * row (family dot + family id + op count) shares its height with
 * ToolLogRow rows (--tool-op-row-height) so the stat cell and its
 * group-ops cell keep one vertical rhythm. Meta lines are
 * caller-supplied preformatted rollups; single-op groups render the
 * header row only — the op's own metric already carries the numbers, so
 * meta lines are suppressed even if passed.
 *
 * Active state: when the in-flight operation belongs to this group, the
 * family name renders orange. Only one block within a card can be
 * active at a time — enforcement is the caller's responsibility.
 *
 * Spec: docs/design-system.md — Molecules → ToolStatBlock.
 */

import React from 'react'
import { StatusDot } from '../atoms/StatusDot'
import type { ExplorationFamily } from '../atoms/ToolCommandText'
import './ToolStatBlock.css'

export interface ToolStatBlockProps {
  family: ExplorationFamily
  opCount: number
  /** Preformatted rollup lines, e.g. "750 lines · 31.4 KB", "4 files".
   *  Not rendered when opCount === 1 (single-op rule). */
  metaLines?: string[]
  /** When > 0, "{n} failed" renders as the last meta line in the
   *  on-navy failure red. Subject to the single-op rule like any other
   *  meta line. */
  failedCount?: number
  active?: boolean
  /** Parent-applied: adjacent stat cells get a top separator; the first
   *  cell has none. */
  notFirst?: boolean
}

function dotStatus(family: ExplorationFamily) {
  return family === 'web_search' || family === 'web_fetch' ? 'web' : family
}

export const ToolStatBlock = React.memo(function ToolStatBlock(
  props: ToolStatBlockProps
) {
  const { family, opCount, metaLines = [], failedCount = 0, active = false, notFirst = false } = props
  const cls = [
    'tsb-cell',
    active && 'tsb-cell--active',
    notFirst && 'tsb-cell--not-first',
  ]
    .filter(Boolean)
    .join(' ')
  const showMeta = opCount !== 1 && (metaLines.length > 0 || failedCount > 0)

  return (
    <div className={cls}>
      <div className="tsb-cell-header">
        <StatusDot status={dotStatus(family)} size="sm" />
        <span className="tsb-cell-name">{family}</span>
        <span className="tsb-cell-opcount">
          {opCount === 1 ? '1 op' : `${opCount} ops`}
        </span>
      </div>
      {showMeta && (
        <div className="tsb-cell-meta">
          {metaLines.map((line, i) => (
            <div key={i} className="tsb-cell-meta-line">{line}</div>
          ))}
          {failedCount > 0 && (
            <div className="tsb-cell-meta-line tsb-cell-meta-line--failed">
              {failedCount} failed
            </div>
          )}
        </div>
      )}
    </div>
  )
})

export default ToolStatBlock
