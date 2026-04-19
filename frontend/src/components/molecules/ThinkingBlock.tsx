/**
 * ThinkingBlock — collapsible container for agent internal reasoning.
 *
 * Lavender background distinguishes thinking from prose output.
 * Contains a label row (navy circle + "THINKING") and the reasoning
 * body text. Collapses to label-only with a toggle indicator.
 *
 * Used in: activity feed, between tool call groups and prose cards.
 */

import { useState, type ReactNode } from 'react'
import './ThinkingBlock.css'

interface ThinkingBlockProps {
  children: ReactNode
  defaultExpanded?: boolean
}

export function ThinkingBlock({ children, defaultExpanded = true }: ThinkingBlockProps) {
  const [expanded, setExpanded] = useState(defaultExpanded)

  return (
    <div className="thinking-block">
      <div
        className="thinking-block__header"
        onClick={() => setExpanded(e => !e)}
      >
        <span className="thinking-block__icon" aria-hidden="true">
          <span className="thinking-block__icon-inner" />
        </span>
        <span className="thinking-block__label">Thinking</span>
        <span className="thinking-block__toggle">{expanded ? '▾' : '▸'}</span>
      </div>
      {expanded && (
        <div className="thinking-block__body">
          {children}
        </div>
      )}
    </div>
  )
}

export default ThinkingBlock
