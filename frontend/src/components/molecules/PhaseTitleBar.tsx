/**
 * PhaseTitleBar — title bar at the top of the content area identifying the
 * current or viewed phase.
 *
 * Active phases show an orange dot and an optional mono subtitle (e.g.
 * "from brief.md"). Completed phases being viewed show a teal dot and a
 * "completed - {elapsed}" badge. Badge and subtitle are mutually exclusive.
 *
 * Used in: content column, top (above ContextCard).
 */

import './PhaseTitleBar.css'

interface PhaseTitleBarProps {
  name: string
  status: 'active' | 'completed'
  subtitle?: string
  elapsed?: string
}

export function PhaseTitleBar({ name, status, subtitle, elapsed }: PhaseTitleBarProps) {
  return (
    <div className="ptb">
      <span className={`ptb__dot ptb__dot--${status}`} />
      <span className="ptb__title">{name}</span>
      {status === 'completed' ? (
        <span className="ptb__badge">completed{elapsed ? ` · ${elapsed}` : ''}</span>
      ) : (
        subtitle && <span className="ptb__subtitle">{subtitle}</span>
      )}
    </div>
  )
}

export default PhaseTitleBar
