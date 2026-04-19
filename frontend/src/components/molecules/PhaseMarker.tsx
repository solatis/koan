/**
 * PhaseMarker -- event divider rendered in the content stream when a
 * phase transition occurs.
 *
 * A teal dot sits on a horizontal rule (acting as a timeline node) with
 * the "Phase:" label, phase name, and description flowing to the right.
 * The content group has bg-base behind it so the rule appears to pass
 * behind it.
 */

import './PhaseMarker.css'

interface PhaseMarkerProps {
  name: string
  description: string
}

export function PhaseMarker({ name, description }: PhaseMarkerProps) {
  return (
    <div className="pm">
      <div className="pm-rule" />
      <div className="pm-row">
        <span className="pm-dot" />
        <span className="pm-label">Phase:</span>
        <span className="pm-name">{name}</span>
        <span className="pm-sep" aria-hidden="true">&middot;</span>
        <span className="pm-desc">{description}</span>
      </div>
    </div>
  )
}

export default PhaseMarker
