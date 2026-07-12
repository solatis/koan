/**
 * ToolCallRow — a single row representing a tool call in the activity stream.
 *
 * Shows a status indicator, tool type label, and the command or file path.
 * Rows stack tightly (--gap-tool-rows) within a tool call group, sitting
 * between prose output cards in the content stream.
 *
 * Family variant: when `family` is set (single-op aggregate fallback and
 * standalone exploration rendering), the indicator column shows the
 * family StatusDot instead of the teal check, the type label shows the
 * family id, and the command slot renders ToolCommandText from
 * `commandData`. Running/error indicators and the container treatment
 * are shared with the default variant. When `family` is absent the row
 * renders exactly as before.
 *
 * Used in: activity feed, between prose cards and thinking blocks.
 */

import React from 'react'
import './ToolCallRow.css'
import { FileChip } from '../atoms/FileChip'
import { StatusDot } from '../atoms/StatusDot'
import { ToolCommandText } from '../atoms/ToolCommandText'
import type { ExplorationFamily, ToolCommandTextProps } from '../atoms/ToolCommandText'
import { formatSize } from '../../hooks/useFileAttachment'
import type { AttachmentEntry } from '../../store/index'

interface ToolCallRowProps {
  tool: string
  command: string
  status?: 'done' | 'running' | 'error'
  /** Optional right-aligned metric text. Examples: "22.8 KB · new",
   *  "2.4s · 140 B out", "3 hunks · ±24 lines". */
  metric?: string
  // Committed uploads attached to this tool call, from tool_completed manifest.
  attachments?: AttachmentEntry[] | null
  /** Family variant: renders the family StatusDot, the family id as the
   *  type label, and ToolCommandText from `commandData`. */
  family?: ExplorationFamily
  commandData?: Omit<ToolCommandTextProps, 'family' | 'running' | 'error'>
  /** Metric styling, as on ToolLogRow: 'fail' → --status-failed,
   *  'zero' → italic muted. */
  metricTone?: 'default' | 'fail' | 'zero'
}

function dotStatus(family: ExplorationFamily) {
  return family === 'web_search' || family === 'web_fetch' ? 'web' : family
}

/** True when commandData carries no displayable field — the plain
 *  `command` string then feeds the container title as a fallback. */
function commandDataEmpty(data?: ToolCallRowProps['commandData']) {
  return !data || Object.values(data).every(v => v == null || v === '')
}

const CheckSvg = () => (
  <svg className="tcr-check" viewBox="0 0 14 14" fill="none" aria-hidden="true">
    <path d="M2.5 7.5L5.5 10.5L11.5 4" stroke="var(--color-teal)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

export const ToolCallRow = React.memo(function ToolCallRow({ tool, command, status = 'done', metric, attachments, family, commandData, metricTone = 'default' }: ToolCallRowProps) {
  const hasAttachments = attachments && attachments.length > 0
  const isFamily = family !== undefined
  const metricClass = [
    'tcr-metric',
    // Running verb renders orange, matching ToolLogRow's --running tone —
    // the family variant's metric formats come from the ToolLogRow table.
    isFamily && status === 'running' && 'tcr-metric--running',
    isFamily && metricTone === 'fail' && 'tcr-metric--fail',
    isFamily && metricTone === 'fail' && 'tcr-metric--fail',
    isFamily && metricTone === 'zero' && 'tcr-metric--zero',
  ]
    .filter(Boolean)
    .join(' ')
  return (
    <div
      className={`tcr tcr--${status}`}
      title={isFamily && commandDataEmpty(commandData) ? command : undefined}
    >
      <span className="tcr-indicator">
        {status === 'done' &&
          (isFamily ? <StatusDot status={dotStatus(family)} size="sm" /> : <CheckSvg />)}
        {status === 'running' && <span className="tcr-running-dot" />}
        {status === 'error' && <span className="tcr-error-x">x</span>}
      </span>
      <span className="tcr-type">{isFamily ? family : tool}</span>
      {isFamily ? (
        <ToolCommandText
          family={family}
          {...(commandData ?? {})}
          running={status === 'running'}
          error={status === 'error'}
        />
      ) : (
        <span className="tcr-command">{command}</span>
      )}
      {metric && <span className={metricClass}>{metric}</span>}
      {hasAttachments && (
        <div className="tcr-attachments">
          {attachments!.map(a => (
            <FileChip key={a.uploadId} name={a.filename} size={formatSize(a.size)} state="ready" />
          ))}
        </div>
      )}
    </div>
  )
})

export default ToolCallRow
