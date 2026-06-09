import { applyPatch } from 'fast-json-patch'
import { KoanStore } from '../store/index'

// Module-level projection dict for patch application.
// fast-json-patch operates on plain JS objects. Patches mutate this object,
// then we spread the result into the Zustand store.
let storeState: Record<string, unknown> = {}

// connectSSE opens an EventSource using always-snapshot catch-up:
//   ?since=0  → server always sends a snapshot event, then live patches
//   ?since=N  → if N !== server.version, still sends snapshot; then live patches
//
// Returns the EventSource so the caller can close it on unmount or reconnect.
// Does NOT schedule its own reconnect — App.tsx owns that lifecycle.
export function connectSSE(store: KoanStore): EventSource {
  const lastVersion = store.getState().lastVersion
  const es = new EventSource(`/events?since=${lastVersion}`)

  store.getState().setConnected(true)

  // -- Snapshot: replace entire store state atomically ----------------------
  es.addEventListener('snapshot', (e) => {
    const { version, state } = JSON.parse((e as MessageEvent).data)
    storeState = state
    store.setState(
      { lastVersion: version, ...state },
      false,
      { type: 'sse/snapshot', version },
    )
  })

  // -- Patch: apply RFC 6902 JSON Patch to store state ----------------------
  es.addEventListener('patch', (e) => {
    try {
      const { version, patch } = JSON.parse((e as MessageEvent).data)
      // mutate:false returns a new document object — avoids mutating state
      // that Zustand may still reference for the current render cycle.
      storeState = applyPatch(storeState, patch, false, false).newDocument
      store.setState(
        { lastVersion: version, ...storeState },
        false,
        { type: 'sse/patch', version, ops: patch },
      )
    } catch (err) {
      console.error('Patch failed, reconnecting for fresh snapshot:', err)
      es.close()
      store.setState({ lastVersion: 0 }, false, 'sse/reset')
      // App.tsx onerror handler schedules the reconnect
    }
  })

  // onerror is overridden by App.tsx to schedule reconnects.
  es.onerror = () => {
    store.getState().setConnected(false)
    es.close()
  }

  return es
}
