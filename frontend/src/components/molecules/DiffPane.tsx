import './DiffPane.css'
import type { ReactNode } from 'react'

interface DiffPaneProps {
  before: ReactNode
  after: ReactNode
}

export function DiffPane({ before, after }: DiffPaneProps) {
  return (
    <div className="dp">
      <div className="dp-col dp-col--before">
        <div className="dp-label">Current</div>
        <div>{before}</div>
      </div>
      <div className="dp-col dp-col--after">
        <div className="dp-label">Proposed</div>
        <div>{after}</div>
      </div>
    </div>
  )
}

export function DiffAdd({ children }: { children: ReactNode }) {
  return <span className="dp-add">{children}</span>
}

export function DiffDel({ children }: { children: ReactNode }) {
  return <span className="dp-del">{children}</span>
}

export default DiffPane
