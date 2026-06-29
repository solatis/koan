/**
 * TimelinePlaceholder — a three-dot placeholder for variable-count future
 * phases (e.g. milestones not yet defined). Communicates "something goes here,
 * count unknown."
 *
 * Used in: TimelineRail (milestone section, before milestones are defined).
 */

import './TimelinePlaceholder.css'

interface TimelinePlaceholderProps {
  label: string
}

export function TimelinePlaceholder({ label }: TimelinePlaceholderProps) {
  return (
    <div className="tl-placeholder">
      <div className="tl-placeholder__row">
        <div className="tl-placeholder__dots">
          <span className="tl-placeholder__dot" />
          <span className="tl-placeholder__dot" />
          <span className="tl-placeholder__dot" />
        </div>
        <span className="tl-placeholder__label">{label}</span>
      </div>
    </div>
  )
}

export default TimelinePlaceholder
