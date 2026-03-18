import { useState } from 'preact/hooks'
import { useStore } from '../../store.js'
import { submitReview } from '../../lib/api.js'

export function ReviewForm({ token }) {
  const { requestId, payload: stories } = useStore(s => s.pendingInput)
  const [approved, setApproved] = useState(() => new Set(stories.map(s => s.storyId)))

  function toggle(storyId) {
    setApproved(prev => {
      const next = new Set(prev)
      if (next.has(storyId)) next.delete(storyId)
      else next.add(storyId)
      return next
    })
  }

  function approveAll() {
    setApproved(new Set(stories.map(s => s.storyId)))
  }

  function submit() {
    const approvedList = stories.filter(s => approved.has(s.storyId)).map(s => s.storyId)
    const skippedList  = stories.filter(s => !approved.has(s.storyId)).map(s => s.storyId)
    submitReview({ token, requestId, approved: approvedList, skipped: skippedList })
  }

  return (
    <div class="phase-inner">
      <h2 class="phase-heading">Review story sketches</h2>
      <p class="phase-status">Review stories before execution begins.</p>

      {stories.map(story => (
        <div
          key={story.storyId}
          class={`review-story ${approved.has(story.storyId) ? 'checked' : ''}`}
          onClick={() => toggle(story.storyId)}
        >
          <div class="review-story-checkbox" />
          <span class="review-story-id">{story.storyId}</span>
          <span class="review-story-title"> — {story.title}</span>
        </div>
      ))}

      <div class="form-actions">
        <button class="btn btn-secondary" onClick={approveAll}>Approve All</button>
        <button class="btn btn-primary" onClick={submit}>Submit</button>
      </div>
    </div>
  )
}
