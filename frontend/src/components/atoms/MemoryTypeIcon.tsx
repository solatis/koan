import './MemoryTypeIcon.css'

type MemoryType = 'decision' | 'lesson' | 'context' | 'procedure'

const LETTERS: Record<MemoryType, string> = {
  decision: 'D',
  lesson: 'L',
  context: 'C',
  procedure: 'P',
}

interface MemoryTypeIconProps {
  type: MemoryType
}

export function MemoryTypeIcon({ type }: MemoryTypeIconProps) {
  return (
    <span className={`atom-memory-type-icon atom-memory-type-icon--${type}`}>
      {LETTERS[type]}
    </span>
  )
}

export default MemoryTypeIcon
