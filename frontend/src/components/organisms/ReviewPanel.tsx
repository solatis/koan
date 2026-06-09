/**
 * ReviewPanel -- on-demand artifact viewer with a single comment textarea.
 *
 * Replaces the old per-block multi-comment apparatus (deleted in M6).
 * The review endpoint changed from /api/artifact-review (deleted in M5)
 * to /api/artifact-comment; the parent passes onSubmit with the new
 * flat (comment, attachments) signature.
 *
 * Markdown rendering flows through <Md>, which routes language-mermaid
 * fences to <MermaidBlock> for inline SVG output. <Md> is the single
 * react-markdown entry point in the frontend; ReviewPanel does not import
 * react-markdown directly.
 *
 * Used in: ReviewView in App.tsx, right content column.
 */

import { useState } from 'react'
import { Md } from '../Md'
import './ReviewPanel.css'

// ReviewSubmitPayload removed in M6 -- replaced by flat (comment, attachments) args.

interface ReviewPanelProps {
  path: string
  content: string
  onSubmit: (comment: string, attachments: string[]) => void
  onClose: () => void
}

export function ReviewPanel({ path, content, onSubmit, onClose }: ReviewPanelProps) {
  const [comment, setComment] = useState('')

  const handleSubmit = () => {
    if (!comment.trim()) {
      // No comment typed -- treat as a plain close rather than a no-op submit.
      onClose()
      return
    }
    onSubmit(comment, [])
    setComment('')
  }

  return (
    <div className="rp">
      <div className="rp-header">
        <span className="rp-path">{path}</span>
        <span className="rp-spacer" />
        <button className="rp-close" onClick={onClose}>Close</button>
      </div>
      <div className="rp-body">
        <Md>{content}</Md>
      </div>
      <div className="rp-footer">
        <textarea
          className="rp-comment"
          placeholder="Leave a comment (optional)..."
          value={comment}
          onChange={e => setComment(e.target.value)}
        />
        <div className="rp-footer-actions">
          <span className="rp-spacer" />
          <button className="rp-submit" onClick={handleSubmit}>
            {comment.trim() ? 'Submit comment' : 'Close'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default ReviewPanel
