import './RationaleBlock.css'
import type { ReactNode } from 'react'

interface RationaleBlockProps {
  children: ReactNode
}

export function RationaleBlock({ children }: RationaleBlockProps) {
  return (
    <div className="rb">
      <div className="rb-label">Rationale</div>
      <div>{children}</div>
    </div>
  )
}

export default RationaleBlock
