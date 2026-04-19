/**
 * YieldPanel -- command panel rendered in the content stream when the
 * orchestrator yields for a phase transition decision.
 *
 * Shows a prompt header and a stack of clickable command rows. At most
 * one row is marked recommended (orange left accent + warm tint).
 *
 * Used in: content stream at koan_yield points.
 */

import './YieldPanel.css'

interface Suggestion {
  id: string
  label: string
  command: string
  recommended?: boolean
}

interface YieldPanelProps {
  prompt: string
  suggestions: Suggestion[]
  onSelect: (suggestion: Suggestion) => void
}

export function YieldPanel({ prompt, suggestions, onSelect }: YieldPanelProps) {
  return (
    <div className="yp">
      <div className="yp-header">{prompt}</div>
      <div className="yp-body">
        {suggestions.map(s => (
          <div
            key={s.id}
            className={`yp-row${s.recommended ? ' yp-row--recommended' : ''}`}
            onClick={() => onSelect(s)}
          >
            <span className={`yp-command${s.recommended ? ' yp-command--recommended' : ''}`}>
              <span className="yp-slash">/</span>{s.id}
            </span>
            <span className="yp-desc">{s.command}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default YieldPanel
