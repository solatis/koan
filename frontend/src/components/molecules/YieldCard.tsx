/**
 * YieldCard — suggestion pills rendered at a koan_yield point.
 *
 * Appears in the content stream as a historical record of the yield, and
 * also pinned above FeedbackInput via ActiveYieldPills when the yield is active.
 *
 * Clicking a pill pre-fills the FeedbackInput textarea via the chatDraft store
 * field. The user reviews the pre-filled text and presses Send — no auto-submit.
 *
 * Used in: content stream (yield entry), pinned above FeedbackInput.
 */

import { useStore } from '../../store/index'
import type { Suggestion } from '../../store/index'
import './YieldCard.css'

interface YieldCardProps {
  suggestions: Suggestion[]
}

export function YieldCard({ suggestions }: YieldCardProps) {
  const setChatDraft = useStore(s => s.setChatDraft)

  if (!suggestions.length) return null

  return (
    <div className="yc">
      <div className="yc-pills">
        {suggestions.map(s => (
          <button
            key={s.id}
            className="yc-pill"
            onClick={() => setChatDraft(s.command || s.label)}
            title={s.command || s.label}
          >
            {s.label}
          </button>
        ))}
      </div>
    </div>
  )
}

export default YieldCard
