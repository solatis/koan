import { useStore } from '../../store.js'

export function ContextAnalysis() {
  const logs = useStore(s => s.logs)

  return (
    <div class="phase-inner">
      <p class="phase-status">Reading your conversation to understand the task...</p>
      {logs.length > 0 && (
        <div class="activity-feed">
          {logs.slice(-4).map((line, i) => (
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
