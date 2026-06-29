/**
 * TimelineDot — a status dot used on the timeline rail for top-level phase
 * nodes. Four states: done, active, future, skipped.
 *
 * Pure visual primitive: status drives appearance, no animation. Positioned
 * relative with z-index so it sits above the rail's connecting line.
 *
 * Used in: TimelinePhaseNode (timeline rail).
 */

import './TimelineDot.css'

type Status = 'done' | 'active' | 'future' | 'skipped'

interface TimelineDotProps {
  status: Status
}

export function TimelineDot({ status }: TimelineDotProps) {
  return <span className={`timeline-dot timeline-dot--${status}`} aria-label={status} />
}

export default TimelineDot
