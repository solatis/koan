/**
 * SteeringBar — queued steering messages from the user.
 *
 * Shows an orange-accented bar with "steering" label and a list of
 * queued messages, each with a "queued" badge. Returns null when
 * there are no messages.
 *
 * Used in: content stream, above the FeedbackInput.
 */

import { Md } from '../Md'
import './SteeringBar.css'

interface SteeringBarProps {
  messages: string[]
}

export function SteeringBar({ messages }: SteeringBarProps) {
  if (messages.length === 0) return null

  return (
    <div className="stb">
      <div className="stb-header">steering</div>
      <div className="stb-messages">
        {messages.map((m, i) => (
          <div key={i} className="stb-msg">
            <span className="stb-badge">queued</span>
            <Md>{m}</Md>
          </div>
        ))}
      </div>
    </div>
  )
}

export default SteeringBar
