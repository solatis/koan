import { KoanStore } from '../store/index'

// connectSSE opens an EventSource using version-negotiated catch-up:
//   ?since=0  → server sends a snapshot event, then live events
//   ?since=N  → server replays events N+1..M, then live events
//
// Returns the EventSource so the caller can close it on unmount or reconnect.
// Does NOT schedule its own reconnect -- App.tsx owns that lifecycle.
export function connectSSE(store: KoanStore): EventSource {
  const lastVersion = store.getState().lastVersion
  const es = new EventSource(`/events?since=${lastVersion}`)

  store.getState().setConnected(true)

  // ── Snapshot: atomic state replace (since=0) ───────────────────────────

  es.addEventListener('snapshot', (e) => {
    const data = JSON.parse((e as MessageEvent).data) as Record<string, unknown>
    store.getState().applySnapshot(data)
  })

  // ── Fatal error: server cannot serve the requested version ─────────────
  // Sent when ?since=N references a version the server no longer has
  // (e.g. after server restart). Close without reconnect; App.tsx renders
  // a "reload required" banner.

  es.addEventListener('fatal_error', () => {
    store.getState().setFatalError(true)
    store.getState().setConnected(false)
    es.close()
    // App.tsx overrides onerror -- but this is a named event, not an error.
    // We do NOT call the reconnect path here. App.tsx checks fatalError
    // in the reconnect scheduler and skips reconnect when it is set.
  })

  // ── All other events: incremental fold ────────────────────────────────

  const KNOWN_EVENTS = [
    'phase_started', 'agent_spawned', 'agent_spawn_failed',
    'agent_step_advanced', 'agent_exited', 'workflow_completed',
    'tool_called', 'tool_completed', 'thinking', 'stream_delta', 'stream_cleared',
    'questions_asked', 'questions_answered',
    'artifact_review_requested', 'artifact_reviewed',
    'workflow_decision_requested', 'workflow_decided',
    'artifact_created', 'artifact_modified', 'artifact_removed',
  ]

  for (const eventType of KNOWN_EVENTS) {
    es.addEventListener(eventType, (e) => {
      const data = JSON.parse((e as MessageEvent).data) as Record<string, unknown>
      store.getState().applyEvent({ event_type: eventType, ...data })
    })
  }

  // onerror is overridden by App.tsx to schedule reconnects.
  es.onerror = () => {
    store.getState().setConnected(false)
    es.close()
  }

  return es
}
