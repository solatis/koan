import { useStore } from './store.js'

export function connectSSE(token) {
  const es = new EventSource(`/events?session=${encodeURIComponent(token)}`)
  const set = useStore.setState

  const handlers = {
    'init':             (d) => set({ availableModels: d.availableModels || [] }),
    phase:              (d) => set({
      phase: d.phase,
      // Clear interaction state and intake progress when leaving intake
      ...(d.phase !== 'intake' && { pendingInput: null, intakeProgress: null }),
    }),
    'intake-progress':  (d) => set({ intakeProgress: d }),
    stories:            (d) => set({ stories: d.stories }),
    scouts:             (d) => set({ scouts: d.scouts }),
    agents:             (d) => set({ agents: d.agents }),
    logs:               (d) => set({ logs: d.lines, currentToolCallId: d.currentToolCallId ?? null }),
    subagent:           (d) => set({ subagent: d }),
    'subagent-idle':    ()  => set({ subagent: null }),
    'pipeline-end':     (d) => set(s => ({
      phase: d.success ? 'completed' : s.phase,
      pipelineEnd: d,
      intakeProgress: null,
    })),
    ask:                (d) => set({ pendingInput: { type: 'ask',    requestId: d.requestId, payload: d.question } }),
    review:             (d) => set({ pendingInput: { type: 'review', requestId: d.requestId, payload: d.stories } }),
    'model-config':           (d) => set(s => ({
      pendingInput: { type: 'model-config', requestId: d.requestId, payload: { ...d.tiers, scoutConcurrency: d.scoutConcurrency } },
      ...(d.availableModels ? { availableModels: d.availableModels } : {}),
    })),
    'model-config-confirmed': ()  => set(s => s.pendingInput?.type === 'model-config' ? { pendingInput: null } : {}),
    'ask-cancelled':    (d) => set(s => s.pendingInput?.requestId === d.requestId
      ? { pendingInput: null, notifications: [...s.notifications, { id: Date.now(), message: 'The question was cancelled — the subagent has exited.', level: 'warning' }] }
      : {}),
    'review-cancelled': (d) => set(s => s.pendingInput?.requestId === d.requestId
      ? { pendingInput: null, notifications: [...s.notifications, { id: Date.now(), message: 'The review was cancelled.', level: 'warning' }] }
      : {}),
    notification:       (d) => set(s => ({
      notifications: [...s.notifications, { id: Date.now(), message: d.message, level: d.level }],
    })),
  }

  for (const [event, handler] of Object.entries(handlers)) {
    es.addEventListener(event, (e) => {
      try { handler(JSON.parse(e.data)) }
      catch (err) { console.error(`[koan] SSE "${event}":`, err) }
    })
  }

  es.onerror = () => set(s => ({
    notifications: [...s.notifications, { id: Date.now(), message: 'Connection lost — reconnecting…', level: 'warning' }],
  }))

  return es
}
