/**
 * ScoutRow -- a single data row in the sub-agent status table.
 *
 * Renders as a CSS grid row conforming to the scout table column template.
 * Shows status dot, name, an optional role badge (scout/executor/reviewer),
 * model badge, tool count, elapsed time, and current step label.
 *
 * M6: accepts an optional role prop and renders a role badge alongside the
 * agent name so reviewer and executor agents are visually distinguishable
 * from scouts. The badge uses the existing Badge atom with variant="model"
 * as the closest available styling; role is rendered in lowercase.
 *
 * Used in: ScoutBar organism.
 */

import { StatusDot } from '../atoms/StatusDot'
import { Badge } from '../atoms/Badge'
import './ScoutRow.css'

interface ScoutRowProps {
  name: string
  /** Sub-agent role string (scout, executor, reviewer). Renders as a badge when provided. */
  role?: string
  model: string
  status: 'running' | 'done' | 'queued' | 'failed'
  tools: number
  elapsed: string
  currentStep: string
}

/** Render one row in the sub-agent status table. */
export function ScoutRow({ name, role, model, status, tools, elapsed, currentStep }: ScoutRowProps) {
  const stepColor = status === 'done' || status === 'failed' ? undefined : 'running'
  return (
    <div className={`sr sr--${status}`}>
      <span className="sr-dot"><StatusDot status={status} size="sm" /></span>
      <span className="sr-name">
        {name}
        {/* Role badge distinguishes reviewer/executor from scouts in the bar. */}
        {role && role !== 'scout' && (
          <span className="sr-role"><Badge variant="model">{role}</Badge></span>
        )}
      </span>
      <span className="sr-model"><Badge variant="model">{model}</Badge></span>
      <span className="sr-tools">{tools}</span>
      <span className="sr-elapsed">{elapsed}</span>
      <span className={`sr-step${stepColor ? ' sr-step--active' : ''}`}>{currentStep}</span>
    </div>
  )
}

export default ScoutRow
