import './ActivityRow.css'
import type { ReactNode } from 'react'

interface ActivityRowProps {
  time: string
  body: ReactNode
}

export function ActivityRow({ time, body }: ActivityRowProps) {
  return (
    <div className="ar">
      <span className="ar-time">{time}</span>
      <span className="ar-body">{body}</span>
    </div>
  )
}

export default ActivityRow
