/**
 * Badge — pill-shaped inline label for metadata and status.
 *
 * Used for: "coming soon", "recommended" (neutral/success), model labels
 * (model), "default" installation labels (default), "unavailable" (error),
 * and other small inline indicators.
 */

import './Badge.css'
import type { ReactNode } from 'react'

type Variant =
  | 'neutral' | 'success' | 'accent' | 'model' | 'default' | 'error'
  | 'decision' | 'lesson' | 'context' | 'procedure'
  | 'add' | 'update' | 'deprecate'

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
