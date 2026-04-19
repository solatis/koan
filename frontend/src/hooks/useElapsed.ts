import { useState, useEffect } from 'react'

export function formatElapsed(ms: number): string {
  const s = Math.floor(ms / 1000)
  const m = Math.floor(s / 60)
  return `${m}m ${String(s % 60).padStart(2, '0')}s`
}

function formatSeconds(ms: number): string {
  return `${Math.floor(ms / 1000)}s`
}

// useElapsed computes a human-readable elapsed time string that updates every
// second. Replaces the DOM-scanning setInterval hack from koan.js that read
// data-started-at attributes.
export function useElapsed(startedAt: number): string {
  const [elapsed, setElapsed] = useState(() => formatElapsed(Date.now() - startedAt))

  useEffect(() => {
    const id = setInterval(() => {
      setElapsed(formatElapsed(Date.now() - startedAt))
    }, 1000)
    return () => clearInterval(id)
  }, [startedAt])

  return elapsed
}

// useElapsedBetween returns a compact seconds-only elapsed string.
// If endedAt is null, it live-ticks. If both are set, it returns the
// static duration.
export function useElapsedBetween(
  startedAt: number | null | undefined,
  endedAt: number | null | undefined,
): string | null {
  const [now, setNow] = useState(Date.now())
  const ticking = startedAt != null && endedAt == null

  useEffect(() => {
    if (!ticking) return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [ticking])

  if (startedAt == null) return null
  const end = endedAt ?? now
  return formatSeconds(end - startedAt)
}
