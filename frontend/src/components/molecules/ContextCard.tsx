/**
 * ContextCard — a handoff card rendered at the top of each phase's content,
 * showing which artifacts the agent received from the previous phase.
 *
 * Not rendered for the first phase (no handoff). When phases were skipped on
 * the way here, the label notes them: "Handoff from Intake (Core Flows skipped)".
 *
 * Used in: content column, below PhaseTitleBar.
 */

import './ContextCard.css'

interface Artifact {
  name: string
  role?: string
}

interface ContextCardProps {
  fromPhase: string
  artifacts: Artifact[]
  skippedPhases?: string[]
}

export function ContextCard({ fromPhase, artifacts, skippedPhases }: ContextCardProps) {
  const skipped =
    skippedPhases && skippedPhases.length > 0 ? ` (${skippedPhases.join(', ')} skipped)` : ''

  return (
    <div className="ctx-card">
      <div className="ctx-card__label">
        Handoff from {fromPhase}
        {skipped}
      </div>
      <div className="ctx-card__files">
        {artifacts.map(a => (
          <div className="ctx-card__file" key={a.name}>
            <span className="ctx-card__filename">{a.name}</span>
            {a.role && <span className="ctx-card__role">{a.role}</span>}
          </div>
        ))}
      </div>
    </div>
  )
}

export default ContextCard
