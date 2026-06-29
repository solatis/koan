/**
 * TimelineHandoff — an artifact badge rendered between top-level phases on the
 * timeline, representing the handoff artifact that connects them.
 *
 * Used in: TimelineRail.
 */

import './TimelineHandoff.css'

interface TimelineHandoffProps {
  name: string
  onClick?: () => void
}

export function TimelineHandoff({ name, onClick }: TimelineHandoffProps) {
  return (
    <div className="tl-handoff" onClick={onClick}>
      <span className="tl-handoff__name">{name}</span>
    </div>
  )
}

export default TimelineHandoff
