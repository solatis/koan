import Badge from './Badge'

type MemoryType = 'decision' | 'lesson' | 'context' | 'procedure'

function capitalize(s: string) {
  return s.charAt(0).toUpperCase() + s.slice(1)
}

interface MemoryTypeBadgeProps {
  type: MemoryType
}

export function MemoryTypeBadge({ type }: MemoryTypeBadgeProps) {
  return <Badge variant={type}>{capitalize(type)}</Badge>
}

export default MemoryTypeBadge
