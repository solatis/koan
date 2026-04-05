/**
 * ProgressSegment — a single bar in the header progress indicator.
 *
 * Composed as a row of segments to show workflow step progress.
 * Used in: header bar (e.g., 3 segments for intake steps).
 */

import './ProgressSegment.css'

type State = 'completed' | 'active' | 'future'

interface ProgressSegmentProps {
  state: State
}

export function ProgressSegment({ state }: ProgressSegmentProps) {
  return (
    <span className={`progress-segment progress-segment--${state}`} />
  )
}

export default ProgressSegment
