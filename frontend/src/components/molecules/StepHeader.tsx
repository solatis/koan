/**
 * StepHeader — step indicator at the top of each step's content stream.
 *
 * Shows "step N/M" in the accent color followed by the step name.
 * Active steps use orange, completed steps use teal.
 *
 * Used in: content stream, for step entry events.
 */

import './StepHeader.css'

interface StepHeaderProps {
  stepNumber: number
  totalSteps: number
  stepName: string
  status?: 'active' | 'complete'
}

export function StepHeader({ stepNumber, totalSteps, stepName, status = 'active' }: StepHeaderProps) {
  const label = totalSteps > 0 ? `step ${stepNumber}/${totalSteps}` : stepName

  return (
    <div className="sh">
      <span className={`sh-label sh-label--${status}`}>{label}</span>
      {stepNumber > 0 && stepName && <span className="sh-name">{stepName}</span>}
    </div>
  )
}

export default StepHeader
