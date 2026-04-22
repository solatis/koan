import './MemoryCard.css'
import MemoryTypeIcon from '../atoms/MemoryTypeIcon'

type MemoryType = 'decision' | 'lesson' | 'context' | 'procedure'

interface MemoryCardProps {
  type: MemoryType
  seq: string
  title: string
  current?: boolean
  onClick?: () => void
}

export function MemoryCard({ type, seq, title, current, onClick }: MemoryCardProps) {
  const cls = `mc${current ? ' mc--current' : ''}`
  const Tag = onClick ? 'button' : 'div'
  return (
    <Tag className={cls} type={onClick ? 'button' : undefined} onClick={onClick}>
      <MemoryTypeIcon type={type} />
      <div className="mc-body">
        <div className="mc-head">
          <span className="mc-seq">{seq}</span>
          <span className="mc-type">{type}</span>
        </div>
        <span className="mc-title">{title}</span>
      </div>
    </Tag>
  )
}

export default MemoryCard
