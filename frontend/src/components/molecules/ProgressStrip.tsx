import './ProgressStrip.css'
import ProgressSegment from '../atoms/ProgressSegment'
import StatCell from '../atoms/StatCell'
import Button from '../atoms/Button'

interface ProgressStripProps {
  turn: number
  maxTurns: number
  elapsed: string
  model: string
  onCancel: () => void
}

function segmentState(i: number, turn: number): 'completed' | 'active' | 'future' {
  if (i < turn - 1) return 'completed'
  if (i === turn - 1) return 'active'
  return 'future'
}

export function ProgressStrip({ turn, maxTurns, elapsed, model, onCancel }: ProgressStripProps) {
  return (
    <div className="ps">
      <StatCell size="sm" value={`${turn} / ${maxTurns}`} label="Turn" />
      <div className="ps-segments">
        {Array.from({ length: maxTurns }, (_, i) => (
          <ProgressSegment key={i} state={segmentState(i, turn)} />
        ))}
      </div>
      <span className="ps-sep">&middot;</span>
      <StatCell size="sm" value={elapsed} label="Elapsed" />
      <span className="ps-sep">&middot;</span>
      <StatCell size="sm" value={model} label="Model" />
      <span className="ps-spacer" />
      <Button variant="danger" size="sm" onClick={onCancel}>Cancel</Button>
    </div>
  )
}

export default ProgressStrip
