import './DecisionPill.css'
import StatusDot from '../atoms/StatusDot'

type State = 'approved' | 'rejected'

const CONFIG: Record<State, { dot: 'done' | 'failed'; label: string }> = {
  approved: { dot: 'done', label: 'Approved' },
  rejected: { dot: 'failed', label: 'Rejected' },
}

interface DecisionPillProps {
  state: State
}

export function DecisionPill({ state }: DecisionPillProps) {
  const { dot, label } = CONFIG[state]
  return (
    <span className={`dpill dpill--${state}`}>
      <StatusDot size="sm" status={dot} />
      {label}
    </span>
  )
}

export default DecisionPill
