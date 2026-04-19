/**
 * UserBubble — the user's own messages in the content stream.
 * Gray left border distinguishes user messages from agent prose (orange).
 * Used in: content stream, for user_message events.
 */
import type { ReactNode } from 'react'
import './UserBubble.css'

interface UserBubbleProps {
  children: ReactNode
  timestamp?: string
}

export function UserBubble({ children, timestamp }: UserBubbleProps) {
  return (
    <div className="ub">
      <div className="ub-content">{children}</div>
      {timestamp && <div className="ub-time">{timestamp}</div>}
    </div>
  )
}

export default UserBubble
