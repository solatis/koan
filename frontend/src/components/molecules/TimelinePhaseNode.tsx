/**
 * TimelinePhaseNode — a clickable phase entry in the timeline rail.
 *
 * Composes TimelineDot. The vertical connecting line is drawn by the node's
 * own ::before so stacked nodes form one continuous line; isFirst / isLast
 * trim it to half-height at the ends of the rail. The `viewing` flag marks the
 * phase whose history the user is currently looking at.
 *
 * Controlled entirely via props — the parent computes the meta string.
 *
 * Used in: TimelineRail.
 */

import { TimelineDot } from '../atoms/TimelineDot'
import './TimelinePhaseNode.css'

type Status = 'done' | 'active' | 'future' | 'skipped'

interface TimelinePhaseNodeProps {
  name: string
  status: Status
  meta?: string
  viewing?: boolean
  isFirst?: boolean
  isLast?: boolean
  onClick?: () => void
}

export function TimelinePhaseNode({
  name,
  status,
  meta,
  viewing,
  isFirst,
  isLast,
  onClick,
}: TimelinePhaseNodeProps) {
  const className = [
    'tl-phase',
    `tl-phase--${status}`,
    viewing && 'tl-phase--viewing',
    isFirst && 'tl-phase--first',
    isLast && 'tl-phase--last',
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <div className={className} onClick={onClick}>
      <div className="tl-phase__row">
        <TimelineDot status={status} />
        <div className="tl-phase__text">
          <span className="tl-phase__name">{name}</span>
          {meta && <span className="tl-phase__meta">{meta}</span>}
        </div>
      </div>
    </div>
  )
}

export default TimelinePhaseNode
