import { useStore } from '../../store.js'

export function Completion() {
  const pipelineEnd = useStore(s => s.pipelineEnd)

  return (
    <div class="phase-inner">
      <p class="phase-status">
        {pipelineEnd?.success ? 'Pipeline complete ✓' : 'Pipeline failed'}
      </p>
      {pipelineEnd?.summary && (
        <div class="summary-list">
          <div class="summary-item">
            <span class={pipelineEnd.success ? 'icon-done' : 'icon-pending'}>
              {pipelineEnd.success ? '✓' : '✗'}
            </span>
            <span>{pipelineEnd.summary}</span>
          </div>
        </div>
      )}
    </div>
  )
}
