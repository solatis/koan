import { useStore } from '../../store.js'

const COLORS = ['var(--blue)', 'var(--purple)', 'var(--orange)', 'var(--yellow)', 'var(--pink)']

export function ScoutExploration() {
  const scouts = useStore(s => s.scouts)

  return (
    <div class="phase-inner">
      <p class="phase-status">
        Exploring your codebase with {scouts.length} scout{scouts.length !== 1 ? 's' : ''}…
      </p>
      {scouts.map((scout, i) => (
        <ScoutCard key={scout.id} scout={scout} color={COLORS[i % COLORS.length]} />
      ))}
      <CompletedContext scouts={scouts} />
    </div>
  )
}

function ScoutCard({ scout, color }) {
  const cls = scout.status === 'completed' ? 'card card-done'
            : scout.status === 'failed'    ? 'card card-failed'
            : 'card card-running'
  const symbol = scout.status === 'completed' ? '✓' : scout.status === 'failed' ? '✗' : '●'

  return (
    <div class={cls} style={scout.status === 'running' ? { borderLeftColor: color } : undefined}>
      <div class="card-header">
        <span class={`agent-status-${scout.status === 'completed' ? 'done' : scout.status}`}>{symbol}</span>
        <span class="card-title" style={scout.status === 'running' ? { color } : undefined}>{scout.id}</span>
        <span class="card-role">{scout.role}</span>
      </div>
      <div class="card-body">
        {scout.status === 'completed' ? scout.completionSummary
         : scout.status === 'failed'  ? <span style={{ color: 'var(--red)' }}>Scout failed</span>
         : <span style={{ color: 'var(--text-dim)' }}>{scout.lastAction || 'Starting…'}</span>}
      </div>
    </div>
  )
}

function CompletedContext({ scouts }) {
  const completed = scouts.filter(s => s.status === 'completed' && s.completionSummary)
  if (completed.length === 0) return null

  return (
    <>
      <div class="context-section-label">CONTEXT SO FAR</div>
      <ul class="context-items">
        {completed.map(s => (
          <li key={s.id}>
            {s.id}: {s.completionSummary?.slice(0, 100)}
            {(s.completionSummary?.length ?? 0) > 100 ? '…' : ''}
          </li>
        ))}
      </ul>
    </>
  )
}
