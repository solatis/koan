/**
 * TimelineSubPhaseNode — a smaller phase node for sub-phases within a milestone
 * group (Plan, Execute). Uses a smaller dot and tighter spacing than a
 * top-level TimelinePhaseNode.
 *
 * Used in: TimelineRail (milestone group sub-phases).
 */

import './TimelineSubPhaseNode.css'

type Status = 'done' | 'active' | 'future'

interface TimelineSubPhaseNodeProps {
  name: string
  status: Status
}

export function TimelineSubPhaseNode({ name, status }: TimelineSubPhaseNodeProps) {
  return (
    <div className={`tl-subphase tl-subphase--${status}`}>
      <span className="tl-subphase__dot" />
      <span className="tl-subphase__name">{name}</span>
    </div>
  )
}

export default TimelineSubPhaseNode
