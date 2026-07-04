/**
 * StepHeader — step indicator at the top of each step's content stream.
 *
 * Shows "step N/M" in the accent color followed by the step name.
 * Active steps use orange, completed steps use teal. The historical prop
 * forces the complete (teal) treatment when viewing a past phase.
 *
 * Used in: content stream, for step entry events.
 */

import React from 'react'
import './StepHeader.css'

interface StepHeaderProps {
  stepNumber: number
  totalSteps: number
  stepName: string
  status?: 'active' | 'complete'
  historical?: boolean
}

export const StepHeader = React.memo(function StepHeader({ stepNumber, totalSteps, stepName, status = 'active', historical }: StepHeaderProps) {
  // historical overrides status to 'complete' so historical-view steps
  // always render in teal regardless of their original step status.
  const effectiveStatus = historical ? 'complete' : status
  const label = totalSteps > 0 ? `step ${stepNumber}/${totalSteps}` : stepName

  return (
    <div className="sh">
      <span className={`sh-label sh-label--${effectiveStatus}`}>{label}</span>
      {stepNumber > 0 && stepName && <span className="sh-name">{stepName}</span>}
    </div>
  )
})

export default StepHeader
