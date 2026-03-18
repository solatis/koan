import { useState, useEffect } from 'preact/hooks'
import { useStore } from '../store.js'
import { formatElapsed } from '../lib/utils.js'

export function Timer() {
  const startedAt = useStore(s => s.subagent?.startedAt)
  const [now, setNow] = useState(Date.now())

  useEffect(() => {
    if (!startedAt) return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [startedAt])

  if (!startedAt) return <span class="timer">—</span>
  return <span class="timer">{formatElapsed(now - startedAt)}</span>
}
