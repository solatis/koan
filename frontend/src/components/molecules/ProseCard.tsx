/**
 * ProseCard — the agent's spoken output surface.
 *
 * White card with an orange left accent border, distinguishing direct
 * agent communication from thinking (lavender) and tool calls (beige).
 * This is the primary text surface in the app.
 *
 * Accepts already-rendered children (from react-markdown or plain JSX).
 *
 * Used in: activity feed, as the main prose output container.
 */

import type { ReactNode } from 'react'
import './ProseCard.css'

interface ProseCardProps {
  children: ReactNode
}

export function ProseCard({ children }: ProseCardProps) {
  return (
    <div className="prose-card">
      {children}
    </div>
  )
}

export default ProseCard
