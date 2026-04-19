/**
 * ReviewEvent -- event divider rendered in the content stream when the
 * user submits an artifact review.
 *
 * Same dot-on-divider pattern as PhaseMarker, but with an orange dot
 * (user action) instead of teal (system event). The file path is shown
 * in monospace orange, followed by a comment-count summary.
 */

import './ReviewEvent.css'

interface ReviewEventProps {
  path: string
  commentCount: number
}

export function ReviewEvent({ path, commentCount }: ReviewEventProps) {
  const summary = `${commentCount} comment${commentCount !== 1 ? 's' : ''} submitted`
  return (
    <div className="re">
      <div className="re-rule" />
      <div className="re-row">
        <span className="re-dot" />
        <span className="re-label">Review:</span>
        <span className="re-name">{path}</span>
        <span className="re-sep" aria-hidden="true">&middot;</span>
        <span className="re-summary">{summary}</span>
      </div>
    </div>
  )
}

export default ReviewEvent
