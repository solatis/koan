/**
 * Badge — pill-shaped inline label for metadata and status.
 *
 * Used for: "coming soon", "recommended", "haiku" model labels,
 * and other small inline indicators throughout the UI.
 */

import './Badge.css'
import type { ReactNode } from 'react'

type Variant = 'neutral' | 'success' | 'accent' | 'model'

interface BadgeProps {
  variant: Variant
  children: ReactNode
}

export function Badge({ variant, children }: BadgeProps) {
  return (
    <span className={`atom-badge atom-badge--${variant}`}>
      {children}
    </span>
  )
}

export default Badge
