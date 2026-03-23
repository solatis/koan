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

export async function fetchArtifacts(token) {
  const resp = await fetch(`/api/artifacts?session=${encodeURIComponent(token)}`)
  if (!resp.ok) throw new Error('Failed to fetch artifacts')
  return resp.json()
}

export async function fetchArtifactContent(token, path) {
  const resp = await fetch(`/api/artifact?session=${encodeURIComponent(token)}&path=${encodeURIComponent(path)}`)
  if (resp.status === 404) throw Object.assign(new Error('File not found'), { status: 404 })
  if (!resp.ok) throw new Error('Failed to fetch artifact content')
  return resp.json()
}
