/**
 * ProseCard — the agent's spoken output surface.
 *
 * White card with an orange left accent border, distinguishing direct
 * agent communication from thinking (lavender) and tool calls (beige).
 * The historical prop switches the accent to teal when viewing a completed
 * phase, visually marking the content as from a past phase.
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
  historical?: boolean
}

export function ProseCard({ children, historical }: ProseCardProps) {
  return (
    <div className={historical ? 'prose-card prose-card--historical' : 'prose-card'}>
      {children}
    </div>
  )
}

export default ProseCard
