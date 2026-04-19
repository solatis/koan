/**
 * StatusDot — a small colored circle indicating either an operational
 * state or a tool family.
 *
 * All variants are static — no animation. In-flight activity indicators
 * in consuming molecules are implemented inline (see ToolCallRow's
 * `.tcr-running-dot` pattern) rather than through StatusDot, so that
 * StatusDot stays a pure visual primitive and adjacent features using
 * StatusDot (e.g. ScoutRow) are unaffected when new variants are added.
 *
 * Used in: header orchestrator indicator, scout table rows, artifact
 * cards, step guidance pill (operational state variants); ToolLogRow and
 * ToolStatBlock (tool-family variants — read, grep, ls).
 */

import './StatusDot.css'

type Status = 'running' | 'done' | 'queued' | 'failed' | 'read' | 'grep' | 'ls'
type Size = 'sm' | 'md'

interface StatusDotProps {
  status: Status
  size?: Size
}

export function StatusDot({ status, size = 'md' }: StatusDotProps) {
  return (
    <span
      className={`status-dot status-dot--${status} status-dot--${size}`}
      aria-label={status}
    />
  )
}

export default StatusDot
