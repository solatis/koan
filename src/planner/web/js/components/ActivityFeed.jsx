import { useRef, useEffect, useState } from 'preact/hooks'
import { useStore } from '../store.js'

export function ActivityFeed() {
  const logs = useStore(s => s.logs)
  const containerRef = useRef(null)
  const stickRef = useRef(true)

  // Track previous last-line to detect in-flight → completed transitions.
  const prevLastRef = useRef(null)
  const [flashIndex, setFlashIndex] = useState(-1)

  // Auto-scroll to bottom when new logs arrive, but only if already at bottom.
  useEffect(() => {
    const el = containerRef.current
    if (el && stickRef.current) {
      el.scrollTop = el.scrollHeight
    }
  }, [logs])

  // Detect when the last line transitions from in-flight to completed and flash it.
  useEffect(() => {
    const lastLine = logs[logs.length - 1]
    if (prevLastRef.current?.inFlight && lastLine && !lastLine.inFlight) {
      const idx = logs.length - 1
      setFlashIndex(idx)
      setTimeout(() => setFlashIndex(-1), 400)
    }
    prevLastRef.current = lastLine ? { ...lastLine } : null
  }, [logs])

  function onScroll() {
    const el = containerRef.current
    if (!el) return
    // "At bottom" if within 30px of the end.
    stickRef.current = el.scrollTop + el.clientHeight >= el.scrollHeight - 30
  }

  if (logs.length === 0) return null

  return (
    <div class="activity-feed-scroll" ref={containerRef} onScroll={onScroll}>
      <div class="activity-feed-inner">
        {logs.map((line, i) => {
          // Only the last line can be in-flight — earlier lines are always done.
          const isInFlight = !!line.inFlight && i === logs.length - 1
          const isFlashing = i === flashIndex
          const cls = [
            'activity-line',
            line.highValue ? 'activity-high' : '',
            isInFlight     ? 'activity-inflight' : '',
            isFlashing     ? 'activity-flash' : '',
          ].filter(Boolean).join(' ')

          return (
            <>
              <div key={i} class={cls}>
                <span class="activity-tool">{line.tool}</span>
                <span class="activity-summary">
                  {line.summary || ''}
                  {isInFlight && <span class="activity-dots">...</span>}
                </span>
              </div>
              {line.details?.map((d, j) => (
                <div key={`${i}-d${j}`} class={`activity-line activity-detail${isInFlight ? ' activity-inflight' : ''}`}>
                  <span class="activity-tool" />
                  <span class="activity-summary">{d}</span>
                </div>
              ))}
            </>
          )
        })}
      </div>
    </div>
  )
}
