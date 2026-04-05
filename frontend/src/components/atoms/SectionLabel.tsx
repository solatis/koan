/**
 * SectionLabel — uppercase label for content sections.
 *
 * Used for: "ARTIFACTS", "SCOUTS", "CONTEXT", "DECISION",
 * "THINKING", and other section headings.
 */

import './SectionLabel.css'
import type { ReactNode } from 'react'

type Color = 'default' | 'teal' | 'orange'

interface SectionLabelProps {
  children: ReactNode
  color?: Color
}

export function SectionLabel({ children, color = 'default' }: SectionLabelProps) {
  return (
    <span className={`section-label section-label--${color}`}>
      {children}
    </span>
  )
}

export default SectionLabel
