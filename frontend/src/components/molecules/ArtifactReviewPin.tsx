/**
 * ArtifactReviewPin -- pinned banner shown while koan_artifact_propose is blocking.
 *
 * Renders when run.activeArtifactReview is non-null and the user is not
 * currently inside the ReviewPanel. Clicking re-opens the ReviewPanel.
 * Gives the user a persistent visual signal that the orchestrator is waiting.
 *
 * Used in: ContentStream, above FeedbackInput.
 */

import './ArtifactReviewPin.css'

interface ArtifactReviewPinProps {
  path: string
  onClick: () => void
}

export function ArtifactReviewPin({ path, onClick }: ArtifactReviewPinProps) {
  return (
    <div className="arp" role="button" tabIndex={0} onClick={onClick}
      onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') onClick() }}>
      <span className="arp-label">Review to continue</span>
      <span className="arp-path">{path}</span>
      <span className="arp-cta">Open review</span>
    </div>
  )
}

export default ArtifactReviewPin
