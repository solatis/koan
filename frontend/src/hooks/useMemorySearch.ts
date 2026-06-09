/**
 * useMemorySearch -- debounced backend search for the memory sidebar.
 *
 * When search is empty, returns { results: null } so callers fall back
 * to the Zustand store entries with client-side type filtering. When
 * non-empty, fires a single request 500 ms after the last keystroke and
 * discards stale responses via a monotonic request-id ref.
 */

import { useState, useEffect, useRef } from 'react'
import type { MemoryEntrySummary, MemoryType } from '../store/index'
import * as api from '../api/client'

const DEBOUNCE_MS = 500

export function useMemorySearch(
  search: string,
  filter: 'all' | MemoryType,
): { results: MemoryEntrySummary[] | null; loading: boolean } {
  const [results, setResults] = useState<MemoryEntrySummary[] | null>(null)
  const [loading, setLoading] = useState(false)

  // Monotonic id: each new request increments this ref. The closure
  // captures the id at call time and ignores the response if a newer
  // request has since been issued.
  const requestId = useRef(0)

  useEffect(() => {
    if (!search) {
      // Empty search: clear results so callers use the store path.
      setResults(null)
      setLoading(false)
      return
    }

    setLoading(true)
    const id = ++requestId.current

    const timer = setTimeout(async () => {
      try {
        const r = await api.listMemoryEntries({
          q: search,
          type: filter === 'all' ? undefined : filter,
        })
        // Drop stale response if a newer request was issued.
        if (id !== requestId.current) return
        // Map wire entries to MemoryEntrySummary (shapes are identical).
        setResults(r.entries as MemoryEntrySummary[])
      } catch {
        if (id !== requestId.current) return
        setResults([])
      } finally {
        if (id === requestId.current) setLoading(false)
      }
    }, DEBOUNCE_MS)

    return () => clearTimeout(timer)
  }, [search, filter])

  return { results, loading }
}
