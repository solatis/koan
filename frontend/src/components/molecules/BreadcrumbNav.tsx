/**
 * BreadcrumbNav — header navigation showing phase, step, and progress.
 *
 * Displays "Phase > Step" breadcrumb text followed by progress segments.
 * Designed for use on a navy (--color-navy) background.
 *
 * Used in: header bar.
 */

import { ProgressSegment } from '../atoms/ProgressSegment'
import './BreadcrumbNav.css'

interface BreadcrumbNavProps {
  phase: string
  step: string
  totalSteps: number
  currentStep: number
}

export function BreadcrumbNav({ phase, step, totalSteps, currentStep }: BreadcrumbNavProps) {
  const segments = Array.from({ length: totalSteps }, (_, i) => {
    const n = i + 1
    if (n < currentStep) return 'completed' as const
    if (n === currentStep) return 'active' as const
    return 'future' as const
  })

  return (
    <nav className="bcn" aria-label="Workflow breadcrumb">
      <span className="bcn-phase">{phase}</span>
      <svg className="bcn-chevron" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M9 6l6 6-6 6" stroke="var(--text-on-dark-subtle)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <span className="bcn-step">{step}</span>
      <span className="bcn-segments">
        {segments.map((state, i) => (
          <ProgressSegment key={i} state={state} />
        ))}
      </span>
    </nav>
  )
}

export default BreadcrumbNav
