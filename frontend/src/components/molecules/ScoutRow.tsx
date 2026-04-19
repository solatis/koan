/**
 * ScoutRow — a single data row in the scout/subagent table.
 *
 * Renders as a CSS grid row conforming to the scout table column
 * template. Shows status dot, name, model badge, tool count,
 * elapsed time, and current step label.
 *
 * Used in: scout bar table (ScoutBar organism, not yet built).
 */

import { StatusDot } from '../atoms/StatusDot'
import { Badge } from '../atoms/Badge'
import './ScoutRow.css'

interface ScoutRowProps {
  name: string
  model: string
  status: 'running' | 'done' | 'queued' | 'failed'
  tools: number
  elapsed: string
  currentStep: string
}

export function ScoutRow({ name, model, status, tools, elapsed, currentStep }: ScoutRowProps) {
  const stepColor = status === 'done' || status === 'failed' ? undefined : 'running'
  return (
    <div className={`sr sr--${status}`}>
      <span className="sr-dot"><StatusDot status={status} size="sm" /></span>
      <span className="sr-name">{name}</span>
      <span className="sr-model"><Badge variant="model">{model}</Badge></span>
      <span className="sr-tools">{tools}</span>
      <span className="sr-elapsed">{elapsed}</span>
      <span className={`sr-step${stepColor ? ' sr-step--active' : ''}`}>{currentStep}</span>
    </div>
  )
}

export default ScoutRow
