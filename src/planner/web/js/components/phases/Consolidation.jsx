import { useStore } from '../../store.js'

export function Consolidation() {
  const logs       = useStore(s => s.logs)
  const scouts     = useStore(s => s.scouts)
  const scoutCount = scouts.length

  return (
    <div class="phase-inner">
      <p class="phase-status">Writing project specification...</p>
      <div class="summary-list">
        <div class="summary-item">
          <span class="icon-done">✓</span>
          <span>Context extracted from conversation</span>
        </div>
        {scoutCount > 0 && (
          <div class="summary-item">
            <span class="icon-done">✓</span>
            <span>{scoutCount} scout{scoutCount !== 1 ? 's' : ''} explored the codebase</span>
          </div>
        )}
        <div class="summary-item">
          <span class="icon-pending">◌</span>
          <span>Writing decisions.md...</span>
        </div>
      </div>
      {logs.length > 0 && (
        <div class="activity-feed" style={{ marginTop: '16px' }}>
          {logs.slice(-3).map((line, i) => (
            <div key={i} class="activity-line">
              <span class="activity-tool">{line.tool}</span>
              <span>{line.summary || ''}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
