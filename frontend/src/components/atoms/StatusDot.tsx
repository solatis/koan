/**
 * StatusDot — a small colored circle indicating operational state.
 *
 * Used in: header orchestrator indicator, scout table rows,
 * artifact cards, step guidance pill.
 */

import './StatusDot.css'

type Status = 'running' | 'done' | 'queued' | 'failed'
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
