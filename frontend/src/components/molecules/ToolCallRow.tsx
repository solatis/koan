/**
 * ToolCallRow — a single row representing a tool call in the activity stream.
 *
 * Shows a status indicator, tool type label, and the command or file path.
 * Rows stack tightly (--gap-tool-rows) within a tool call group, sitting
 * between prose output cards in the content stream.
 *
 * Used in: activity feed, between prose cards and thinking blocks.
 */

import './ToolCallRow.css'
import { FileChip } from '../atoms/FileChip'
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
}

const CheckSvg = () => (
  <svg className="tcr-check" viewBox="0 0 14 14" fill="none" aria-hidden="true">
    <path d="M2.5 7.5L5.5 10.5L11.5 4" stroke="var(--color-teal)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

export function ToolCallRow({ tool, command, status = 'done', metric, attachments }: ToolCallRowProps) {
  const hasAttachments = attachments && attachments.length > 0
  return (
    <div className={`tcr tcr--${status}`}>
      <span className="tcr-indicator">
        {status === 'done' && <CheckSvg />}
        {status === 'running' && <span className="tcr-running-dot" />}
        {status === 'error' && <span className="tcr-error-x">x</span>}
      </span>
      <span className="tcr-type">{tool}</span>
      <span className="tcr-command">{command}</span>
      {metric && <span className="tcr-metric">{metric}</span>}
      {hasAttachments && (
        <div className="tcr-attachments">
          {attachments!.map(a => (
            <FileChip key={a.uploadId} name={a.filename} size={formatSize(a.size)} state="ready" />
          ))}
        </div>
      )}
    </div>
  )
}

export default ToolCallRow
