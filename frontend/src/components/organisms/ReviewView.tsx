/**
 * ReviewView -- artifact review overlay.
 *
 * Reads the currently-reviewed artifact path via selectReviewingArtifact
 * (narrow selector).  Fetches artifact content on path change (with
 * cancellation on unmount / path change).  Submits a flat comment + optional
 * attachments to /api/artifact-comment.
 *
 * Moved from App.tsx to this module in M5.
 */

import { useState, useEffect } from 'react'
import { useStore } from '../../store/index'
import { selectReviewingArtifact } from '../../store/selectors'
import * as api from '../../api/client'
import { ReviewPanel } from './ReviewPanel'

export function ReviewView() {
  const path = useStore(selectReviewingArtifact)
  const setReviewing = useStore(s => s.setReviewingArtifact)
  const [content, setContent] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!path) return
    setContent(null)
    setError(null)
    let cancelled = false
    api.getArtifactContent(path)
      .then(res => { if (!cancelled) setContent(res.content) })
      .catch(e => { if (!cancelled) setError(String(e)) })
    return () => { cancelled = true }
  }, [path])

  if (!path) return null

  // Submit to /api/artifact-comment (M5 endpoint). Flat schema: path + comment
  // + attachments. The old /api/artifact-review and multi-block payload are gone.
  const handleSubmit = (comment: string, attachments: string[]) => {
    api.submitArtifactComment(path, comment, attachments)
    setReviewing(null)
  }

  return (
    <div className="content-column" style={{ padding: '28px 32px 40px 32px' }}>
      {content === null && !error && <div className="loading-center">loading...</div>}
      {error && <div className="loading-center">Error: {error}</div>}
      {content !== null && (
        <ReviewPanel
          path={path}
          content={content}
          onSubmit={handleSubmit}
          onClose={() => setReviewing(null)}
        />
      )}
    </div>
  )
}
