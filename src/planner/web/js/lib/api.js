import { useStore } from '../store.js'

export async function submitAnswers({ token, requestId, answers }) {
  const resp = await fetch('/api/answer', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token, requestId, answers }),
  })
  if (resp.ok) {
    useStore.setState({ pendingInput: null })
  } else {
    console.error('Failed to submit answers:', await resp.text())
  }
}

export async function submitReview({ token, requestId, approved, skipped }) {
  const resp = await fetch('/api/review', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token, requestId, approved, skipped }),
  })
  if (resp.ok) {
    useStore.setState({ pendingInput: null })
  } else {
    console.error('Failed to submit review:', await resp.text())
  }
}
