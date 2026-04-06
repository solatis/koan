/**
 * CompletionBanner — phase completion message.
 *
 * Teal-green banner for successful completion, red-bordered for errors.
 *
 * Used in: completion view, at the top of the content stream.
 */

import type { ReactNode } from 'react'
import './CompletionBanner.css'

interface CompletionBannerProps {
  children: ReactNode
  variant?: 'success' | 'error'
}

export function CompletionBanner({ children, variant = 'success' }: CompletionBannerProps) {
  return (
    <div className={`cb cb--${variant}`}>{children}</div>
  )
}

export default CompletionBanner
