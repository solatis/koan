/**
 * CompletionView -- run completion screen (success banner or failure banner).
 *
 * Reads completion and artifacts via narrow shared selectors.  On success, a
 * timed auto-navigate fires from App (3s); this component just renders the
 * success banner.  On failure, renders an optional "Back to overview" button
 * via the onBackToOverview prop supplied by App.
 *
 * Moved from App.tsx to this module in M5.
 */

import { useStore } from '../../store/index'
import { selectCompletion, selectArtifacts } from '../../store/selectors'
import { Button } from '../atoms/Button'
import { CompletionBanner } from '../molecules/CompletionBanner'
import { ProseCard } from '../molecules/ProseCard'

export function CompletionView(props: { onBackToOverview?: () => void }) {
  const completion = useStore(selectCompletion)
  const artifacts = useStore(selectArtifacts)
  if (!completion) return null
  return (
    <div className="content-column">
      <div className="content-stream">
        {completion.success ? (
          <>
            <CompletionBanner>{completion.summary || 'All phases completed successfully.'}</CompletionBanner>
            {Object.keys(artifacts).length > 0 && (
              <ProseCard>
                <p><strong>Artifacts produced:</strong></p>
                <ul>{Object.keys(artifacts).map(p => <li key={p}><code>{p}</code></li>)}</ul>
              </ProseCard>
            )}
          </>
        ) : (
          <>
            <CompletionBanner variant="error">{completion.error || 'An error occurred.'}</CompletionBanner>
            {props.onBackToOverview && (
              <div className="completion-actions">
                {/* Button visible only on failure; success auto-navigates on a timer. */}
                <Button variant="secondary" onClick={props.onBackToOverview}>Back to overview</Button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
