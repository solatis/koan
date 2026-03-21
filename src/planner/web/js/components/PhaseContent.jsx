import { useStore } from '../store.js'
import { Loading } from './phases/Loading.jsx'
import { Completion } from './phases/Completion.jsx'
import { QuestionForm } from './forms/QuestionForm.jsx'
import { ReviewForm } from './forms/ReviewForm.jsx'
import { ArtifactReview } from './forms/ArtifactReview.jsx'
import { ModelConfig } from './ModelConfig.jsx'

export function PhaseContent({ token, topic }) {
  const phase = useStore(s => s.phase)
  const pending = useStore(s => s.pendingInput)

  // Settings overlay
  const showSettings = useStore(s => s.showSettings)
  if (showSettings) {
    return <ModelConfig token={token} isGate={false} onClose={() => useStore.setState({ showSettings: false })} />
  }

  // Model config gate (startup)
  if (pending?.type === 'model-config') {
    return <ModelConfig token={token} isGate={true} />
  }

  if (!phase) return <Loading topic={topic} />

  if (pending?.type === 'ask') return <QuestionForm key={pending.requestId} token={token} />
  if (pending?.type === 'review') return <ReviewForm key={pending.requestId} token={token} />
  if (pending?.type === 'artifact-review') return <ArtifactReview key={pending.requestId} token={token} />

  if (phase === 'completed') return <Completion />

  // For running phases, App renders ActivityFeed directly — this shouldn't be reached
  return null
}
