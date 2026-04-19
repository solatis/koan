/**
 * ToolLogRow — a compact log row for the right pane of ToolAggregateCard.
 *
 * Visually lighter than ToolCallRow — no background fill, no text type
 * label. The leading dot encodes the tool family via color:
 * read/grep/ls each get their tool-family hue from StatusDot; the
 * in-flight `running` variant uses an inline pulsing orange dot (not
 * StatusDot, because StatusDot stays static for consistency with
 * ScoutRow — see design-system.md § StatusDot).
 *
 * Used in: ToolAggregateCard right pane (not yet built — this molecule
 * is delivered ahead of the card).
 */

import { StatusDot } from '../atoms/StatusDot'
import './ToolLogRow.css'

interface ToolLogRowProps {
  /** Tool family for completed ops (drives dot color), or 'running' for
   *  the in-flight op (drives both the pulsing dot and the muted-text
   *  styling). Completed and in-flight states always move together, so
   *  one prop controls both. */
  status: 'read' | 'grep' | 'ls' | 'running'
  command: string
  /** Optional right-aligned metric text. Examples: "400 lines · 16.1 KB",
   *  "46 matches · 6 files", "7 entries". When status is 'running', the
   *  metric typically reads like "reading…" or "grepping…". */
  metric?: string
}

export function ToolLogRow({ status, command, metric }: ToolLogRowProps) {
  const isRunning = status === 'running'
  return (
    <div className={`tlr tlr--${status}`}>
      {isRunning ? (
        // Inline pulsing dot — intentionally NOT StatusDot. See file header.
        <span className="tlr-running-dot" aria-label="running" />
      ) : (
        <StatusDot status={status} size="sm" />
      )}
      <span className="tlr-command">{command}</span>
      {metric && <span className="tlr-metric">{metric}</span>}
    </div>
  )
}

export default ToolLogRow
