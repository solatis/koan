/**
 * TimelineSubArtifact — a smaller artifact badge between sub-phases within a
 * milestone group. Visually subordinate to TimelineHandoff.
 *
 * Used in: TimelineRail (milestone group sub-phases).
 */

import './TimelineSubArtifact.css'

interface TimelineSubArtifactProps {
  name: string
}

export function TimelineSubArtifact({ name }: TimelineSubArtifactProps) {
  return (
    <div className="tl-subartifact">
      <span className="tl-subartifact__name">{name}</span>
    </div>
  )
}

export default TimelineSubArtifact
