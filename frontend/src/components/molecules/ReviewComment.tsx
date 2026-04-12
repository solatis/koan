/**
 * ReviewComment -- read-only comment card displayed below an anchor block
 * inside a ReviewPanel. Gray left accent on the white parent surface
 * (user-content convention). A delete button appears on hover.
 */

import type { MouseEvent } from 'react'
import './ReviewComment.css'

interface ReviewCommentProps {
  text: string
  onDelete?: () => void
}

export function ReviewComment({ text, onDelete }: ReviewCommentProps) {
  const handleDelete = (e: MouseEvent) => {
    e.stopPropagation()
    onDelete?.()
  }

  return (
    <div className="rc-comment">
      <div className="rc-comment-header">
        <span className="rc-comment-meta">You &middot; just now</span>
        {onDelete && (
          <button
            type="button"
            className="rc-comment-delete"
            onClick={handleDelete}
            aria-label="Delete comment"
          >&times;</button>
        )}
      </div>
      <div className="rc-comment-text">{text}</div>
    </div>
  )
}

export default ReviewComment
