import { useState } from 'preact/hooks'
import { marked } from 'marked'
import { useStore } from '../../store.js'

export function ArtifactReview({ token }) {
  const { requestId, payload } = useStore(s => s.pendingInput)
  const { content, description } = payload

  const [feedback, setFeedback] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const renderedHtml = marked.parse(content)

  async function submit(feedbackText) {
    if (submitting) return
    setSubmitting(true)
    try {
      const resp = await fetch('/api/artifact-review', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, requestId, feedback: feedbackText }),
      })
      if (!resp.ok) {
        console.error('Failed to submit artifact review:', await resp.text())
        setSubmitting(false)
      }
      // On success, the server sends an SSE event that clears pendingInput
    } catch (err) {
      console.error('Failed to submit artifact review:', err)
      setSubmitting(false)
    }
  }

  function handleAccept() {
    submit('Accept')
  }

  function handleSendFeedback() {
    if (!feedback.trim()) return
    submit(feedback.trim())
  }

  return (
    <div class="phase-inner">
      <h2 class="phase-heading">Review Artifact</h2>
      {description && (
        <p class="phase-status">{description}</p>
      )}

      <div
        class="artifact-review-content"
        dangerouslySetInnerHTML={{ __html: renderedHtml }}
      />

      <textarea
        class="artifact-review-feedback"
        placeholder="Feedback (optional — leave blank and click Accept to approve)"
        value={feedback}
        onInput={e => setFeedback(e.target.value)}
        disabled={submitting}
      />

      <div class="form-actions">
        <button
          class="btn btn-secondary"
          onClick={handleSendFeedback}
          disabled={submitting || !feedback.trim()}
        >
          Send Feedback
        </button>
        <button
          class="btn btn-primary"
          onClick={handleAccept}
          disabled={submitting}
        >
          Accept ✓
        </button>
      </div>
    </div>
  )
}
