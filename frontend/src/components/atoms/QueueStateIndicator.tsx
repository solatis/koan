import './QueueStateIndicator.css'

type State = 'pending' | 'approved' | 'rejected'

const GLYPHS: Record<Exclude<State, 'pending'>, string> = {
  approved: '\u2713',
  rejected: '\u2715',
}

interface QueueStateIndicatorProps {
  state: State
  index: number
}

export function QueueStateIndicator({ state, index }: QueueStateIndicatorProps) {
  return (
    <span className={`atom-queue-state atom-queue-state--${state}`}>
      {state === 'pending' ? index : GLYPHS[state]}
    </span>
  )
}

export default QueueStateIndicator
