/**
 * ToolLogRow — one operation line inside a ToolAggregateCard group-ops
 * cell.
 *
 * No leading family dot — family identity lives on the group's stat
 * block, not per row. The only leading indicator is the pulsing orange
 * dot on an in-flight row (inline, intentionally NOT StatusDot, which
 * stays static for consistency with ScoutRow — see design-system.md
 * § StatusDot). Command content renders through ToolCommandText; the
 * metric string is caller-supplied and preformatted.
 *
 * Spec: docs/design-system.md — Molecules → ToolLogRow.
 */

import React from 'react'
import { ToolCommandText } from '../atoms/ToolCommandText'
import type { ExplorationFamily, ToolCommandTextProps } from '../atoms/ToolCommandText'
import './ToolLogRow.css'

export interface ToolLogRowProps {
  family: ExplorationFamily
  command: Omit<ToolCommandTextProps, 'family' | 'running' | 'error'>
  /** Preformatted metric, e.g. "80 lines · 3.9 KB", "exit 0 · 5 lines";
   *  for running rows the in-progress verb, e.g. "reading…". */
  metric?: string
  status?: 'done' | 'running' | 'error'
  /** Metric styling: 'fail' → --status-failed (non-zero bash exit),
   *  'zero' → italic muted (zero-match grep — informative, not red). */
  metricTone?: 'default' | 'fail' | 'zero'
}

export const ToolLogRow = React.memo(function ToolLogRow(
  props: ToolLogRowProps
) {
  const { family, command, metric, status = 'done', metricTone = 'default' } = props
  const running = status === 'running'
  const error = status === 'error'
  const metricClass = [
    'tool-log-op-metric',
    running && 'tool-log-op-metric--running',
    (error || metricTone === 'fail') && 'tool-log-op-metric--fail',
    !running && !error && metricTone === 'zero' && 'tool-log-op-metric--zero',
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <div className="tool-log-op">
      {running && <span className="tool-log-running-dot" aria-label="running" />}
      <ToolCommandText family={family} {...command} running={running} error={error} />
      {metric && <span className={metricClass}>{metric}</span>}
    </div>
  )
})

export default ToolLogRow
