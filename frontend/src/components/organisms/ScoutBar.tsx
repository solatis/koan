/**
 * ScoutBar — navy-framed bottom panel showing running subagents.
 *
 * Contains a summary line (dot + label + counts) and a white table
 * card with column headers and ScoutRow molecules. Returns null
 * when there are no scouts to display.
 *
 * Used in: workspace layout, below the content+sidebar grid.
 */

import { StatusDot } from '../atoms/StatusDot'
import { ScoutRow } from '../molecules/ScoutRow'
import './ScoutBar.css'

interface ScoutEntry {
  name: string
  model: string
  status: 'running' | 'done' | 'queued' | 'failed'
  tools: number
  elapsed: string
  currentStep: string
}

interface ScoutBarProps {
  scouts: ScoutEntry[]
}

type StatusKey = 'running' | 'queued' | 'done' | 'failed'
const STATUS_ORDER: StatusKey[] = ['running', 'queued', 'done', 'failed']

export function ScoutBar({ scouts }: ScoutBarProps) {
  if (scouts.length === 0) return null

  const counts: Record<StatusKey, number> = { running: 0, queued: 0, done: 0, failed: 0 }
  for (const s of scouts) counts[s.status]++

  // Hide when all scouts have finished (no running or queued)
  if (counts.running === 0 && counts.queued === 0) return null

  return (
    <div className="sb">
      <div className="sb-inner">
      {/* Summary line */}
      <div className="sb-summary">
        <div className="sb-summary-left">
          <StatusDot status="running" />
          <span className="sb-label">Scouts</span>
        </div>
        <div className="sb-counts">
          {STATUS_ORDER.map(key => (
            <span key={key} className="sb-count-group">
              <span className={`sb-count-num${counts[key] > 0 ? ` sb-count--${key}` : ''}`}>
                {counts[key]}
              </span>
              <span className="sb-count-word">{key}</span>
            </span>
          ))}
        </div>
      </div>

      {/* Table card */}
      <div className="sb-table">
        <div className="sb-table-header">
          <span />
          <span>name</span>
          <span>model</span>
          <span>tools</span>
          <span>elapsed</span>
          <span>status</span>
        </div>
        {scouts.map((s, i) => (
          <ScoutRow key={i} {...s} />
        ))}
      </div>
      </div>
    </div>
  )
}

export default ScoutBar
