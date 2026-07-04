/**
 * ToolAggregateCard (organism) — family-grouped two-pane card for a run
 * of 2+ consecutive exploration operations.
 *
 * The body is one grid: each FamilyGroup contributes a pair of cells —
 * its navy ToolStatBlock and its stack of ToolLogRows. Because both are
 * cells of the same grid row, the stat header top-aligns with the
 * group's first op row by construction, and the stacked stat cells form
 * the navy column (no wrapper pane element).
 *
 * No orange left border — deliberate, documented deviation from the
 * "left border = content source" convention; the navy header band is
 * the card's identity (see design rationale).
 *
 * Grouping lives outside the card (groupExplorationOps), keeping the
 * organism pure layout. Not yet wired into ContentStream — the live
 * stream keeps rendering the old molecules/ToolAggregateCard until the
 * integration pass.
 *
 * Spec: docs/design-system.md — Organisms → ToolAggregateCard.
 */

import { Fragment } from 'react'
import { ToolStatBlock } from '../molecules/ToolStatBlock'
import { ToolLogRow } from '../molecules/ToolLogRow'
import type { FamilyGroup } from './toolAggregateGrouping'
import './ToolAggregateCard.css'

export interface ToolAggregateCardProps {
  /** Ordered family groups from groupExplorationOps. */
  groups: FamilyGroup[]
  operationCount: number
  /** When set, the card is active: the header renders the pulsing dot
   *  plus this label (e.g. "grepping ReflectTraceEvent"). */
  runningLabel?: string
  elapsed?: string
}

export function ToolAggregateCard({
  groups,
  operationCount,
  runningLabel,
  elapsed,
}: ToolAggregateCardProps) {
  return (
    <div className="tagg">
      <div className="tagg-header">
        <span className="tagg-label">explore</span>
        <span className="tagg-opcount">
          {operationCount === 1 ? '1 operation' : `${operationCount} operations`}
        </span>
        <span className="tagg-spacer" />
        {runningLabel && (
          <span className="tagg-running">
            <span className="tagg-running-dot" aria-label="running" />
            {runningLabel}
          </span>
        )}
        {elapsed && <span className="tagg-elapsed">{elapsed}</span>}
      </div>
      <div className="tagg-body">
        {groups.map((group, i) => (
          <Fragment key={`${group.family}-${i}`}>
            <ToolStatBlock
              family={group.family}
              opCount={group.opCount}
              metaLines={group.metaLines}
              failedCount={group.failedCount}
              active={group.active}
              notFirst={i > 0}
            />
            <div className={`tagg-ops${i > 0 ? ' tagg-ops--not-first' : ''}`}>
              {group.ops.map(op => (
                <ToolLogRow
                  key={op.seq}
                  family={op.family}
                  command={op.command}
                  metric={op.metric}
                  status={op.status}
                  metricTone={op.metricTone}
                />
              ))}
            </div>
          </Fragment>
        ))}
      </div>
    </div>
  )
}

export default ToolAggregateCard
