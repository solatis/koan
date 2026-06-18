// SSE patch applicator: structural sharing via Immer + per-frame coalescing.
//
// Each incoming patch event pushes RFC 6902 ops into a buffer. A single
// requestAnimationFrame flush applies all buffered ops in one Immer produce
// call (structural sharing: only touched paths get new references) and commits
// one setState per frame. This bounds render frequency under fine-grained
// token streams and keeps untouched subtrees reference-stable so narrow
// selectors (entries, settings, ...) skip re-renders during token streaming.
//
// Reconnect path: the server always sends a snapshot first, which cancels any
// pending frame and replaces storeState atomically. The snapshot handler is
// the authoritative buffer reset; the onerror handler below is defense-in-
// depth for the case where connectSSE is used without the App.tsx override.

import { produce } from 'immer'
import { applyPatch, type Operation } from 'fast-json-patch'
import { KoanStore } from '../store/index'

// Module-level projection dict shared across handlers.
// Must remain plain-object; Immer produce returns frozen output after the
// first patch, which is fine -- produce re-drafts from frozen input correctly.
let storeState: Record<string, unknown> = {}

// Coalescing state: buffer ops between rAF flushes.
let pendingOps: Operation[] = []
let pendingVersion = 0
let rafHandle: number | null = null

/**
 * Flush buffered patch ops to the store in a single Immer produce + setState.
 *
 * Coalescing contract: all ops that arrived since the last flush are applied
 * in one produce call, yielding structural sharing (only paths touched by the
 * ops get new references). A single setState follows so React batches exactly
 * one render per animation frame regardless of how many patch events arrived.
 *
 * On apply failure the EventSource is closed and lastVersion is reset to 0 so
 * the next connectSSE call requests a fresh snapshot. App.tsx's reconnect
 * loop sees the closed connection and reschedules connect() via the error path.
 */
function flush(store: KoanStore, es: EventSource): void {
  rafHandle = null
  if (pendingOps.length === 0) return
  const ops = pendingOps
  pendingOps = []
  const version = pendingVersion
  try {
    storeState = produce(storeState, (draft) => {
      // mutateDocument=true: fast-json-patch mutates the Immer draft in place,
      // which is exactly what Immer expects. Return value is not used.
      applyPatch(draft as object, ops, false, true)
    })
  } catch (err) {
    console.error('Patch apply failed, reconnecting for fresh snapshot:', err)
    pendingOps = []
    es.close()
    store.setState({ lastVersion: 0 }, false, 'sse/reset')
    return
  }
  store.setState(
    { lastVersion: version, ...storeState },
    false,
    { type: 'sse/patch', version },
  )
}

// connectSSE opens an EventSource using always-snapshot catch-up:
//   ?since=0  -> server always sends a snapshot event, then live patches
//   ?since=N  -> if N !== server.version, still sends snapshot; then live patches
//
// Returns the EventSource so the caller can close it on unmount or reconnect.
// Does NOT schedule its own reconnect -- App.tsx owns that lifecycle.
export function connectSSE(store: KoanStore): EventSource {
  const lastVersion = store.getState().lastVersion
  const es = new EventSource(`/events?since=${lastVersion}`)

  store.getState().setConnected(true)

  // -- Snapshot: cancel any pending frame, replace entire store state atomically
  es.addEventListener('snapshot', (e) => {
    // A snapshot is authoritative -- discard any buffered ops that arrived
    // before this snapshot (e.g. after a reconnect). The server guarantees
    // the snapshot is consistent with the version it sends.
    if (rafHandle !== null) {
      cancelAnimationFrame(rafHandle)
      rafHandle = null
    }
    pendingOps = []
    const { version, state } = JSON.parse((e as MessageEvent).data)
    storeState = state
    store.setState(
      { lastVersion: version, ...state },
      false,
      { type: 'sse/snapshot', version },
    )
  })

  // -- Patch: buffer ops and schedule a single rAF flush per frame
  es.addEventListener('patch', (e) => {
    try {
      const { version, patch } = JSON.parse((e as MessageEvent).data)
      pendingOps.push(...patch)
      pendingVersion = version
      // Schedule exactly one flush per frame; ignore if one is already pending.
      if (rafHandle === null) {
        rafHandle = requestAnimationFrame(() => flush(store, es))
      }
    } catch (err) {
      console.error('Patch parse failed, reconnecting for fresh snapshot:', err)
      // Clear buffer to avoid stale ops compounding after the reconnect.
      if (rafHandle !== null) { cancelAnimationFrame(rafHandle); rafHandle = null }
      pendingOps = []
      es.close()
      store.setState({ lastVersion: 0 }, false, 'sse/reset')
    }
  })

  // onerror is overridden by App.tsx to schedule reconnects.
  // Buffer cleanup here is defense-in-depth for non-App.tsx callers only.
  es.onerror = () => {
    if (rafHandle !== null) { cancelAnimationFrame(rafHandle); rafHandle = null }
    pendingOps = []
    store.getState().setConnected(false)
    es.close()
  }

  return es
}
