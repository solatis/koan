/**
 * StepGuidancePill — clickable toggle pill for step guidance content.
 *
 * Sits at the top of each step's content stream, above the first
 * thinking block. Shows a colored dot (orange=active, teal=complete),
 * a label, and a chevron that rotates when expanded.
 *
 * Used in: activity feed, at the beginning of each step.
 */

import { useState, type ReactNode } from 'react'
import './StepGuidancePill.css'

interface StepGuidancePillProps {
  status?: 'active' | 'complete'
  children?: ReactNode
  defaultExpanded?: boolean
}

export function StepGuidancePill({ status = 'active', children, defaultExpanded = false }: StepGuidancePillProps) {
  const [expanded, setExpanded] = useState(defaultExpanded)

  return (
    <div className="sgp-wrapper">
      <button
        className="sgp"
        onClick={() => setExpanded(e => !e)}
        aria-expanded={expanded}
      >
        <span className={`sgp-dot sgp-dot--${status}`} />
        <span className="sgp-label">step guidance</span>
        <svg className={`sgp-chevron${expanded ? ' sgp-chevron--up' : ''}`} viewBox="0 0 10 6" fill="none" aria-hidden="true">
          <path d="M1 1l4 4 4-4" stroke="var(--text-subtle)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {expanded && children && (
        <div className="sgp-content">{children}</div>
      )}
    </div>
  )
}

export default StepGuidancePill
