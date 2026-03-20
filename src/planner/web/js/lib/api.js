import { useStore } from '../store.js'

export async function submitAnswers({ token, requestId, answer }) {
  try {
    const resp = await fetch('/api/answer', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token, requestId, answer }),
    })
    if (resp.ok) {
      useStore.setState({ pendingInput: null })
    } else {
      console.error('Failed to submit answers:', await resp.text())
    }
  } catch (err) {
    console.error('Failed to submit answers:', err)
  }
}

export async function submitReview({ token, requestId, approved, skipped }) {
  try {
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
  } catch (err) {
    console.error('Failed to submit review:', err)
  }
}
