import { useStore } from '../store.js'

const PHASE_ORDER = ['intake', 'decomposition', 'review', 'executing', 'completed']

export function ProgressBar() {
  const phase = useStore(s => s.phase)
  const idx = PHASE_ORDER.indexOf(phase || '')
  const pct = idx < 0 ? 0 : (idx / (PHASE_ORDER.length - 1)) * 100

  return (
    <div class="progress-bar">
      <div class="progress-fill" style={{ width: pct + '%' }} />
    </div>
  )
}
