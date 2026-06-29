/**
 * MilestoneNumber — a numbered circle used as the milestone group header node
 * on the timeline rail. Three states: done, active, future.
 *
 * Pure visual primitive. Positioned relative with z-index so it sits above the
 * rail's connecting line.
 *
 * Used in: TimelineRail (milestone group header).
 */

import './MilestoneNumber.css'

type Status = 'done' | 'active' | 'future'

interface MilestoneNumberProps {
  number: number
  status: Status
}

export function MilestoneNumber({ number, status }: MilestoneNumberProps) {
  return <span className={`milestone-number milestone-number--${status}`}>{number}</span>
}

export default MilestoneNumber
