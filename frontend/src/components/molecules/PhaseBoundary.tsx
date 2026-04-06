/**
 * PhaseBoundary — visual separator between workflow phases.
 * A centered label between two horizontal lines.
 * Used in: content stream, for phase_boundary events.
 */
import './PhaseBoundary.css'

interface PhaseBoundaryProps {
  label: string
}

export function PhaseBoundary({ label }: PhaseBoundaryProps) {
  return (
    <div className="pb">
      <span className="pb-line" />
      <span className="pb-label">{label}</span>
      <span className="pb-line" />
    </div>
  )
}

export default PhaseBoundary
