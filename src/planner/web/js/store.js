// Zustand store and SSE event->state handlers.
//
// store.js owns both the store shape and the event->state mapping.
// sse.js only knows event type names and raw payloads -- it imports
// named handler functions from here and never calls useStore directly.
// Changing the store shape only requires updating this file.

import { create } from 'zustand'

export const useStore = create((set) => ({
  // Server-pushed state
  phase: null,
  stories: [],
  scouts: [],
  agents: [],
  logs: [],                  // Array<{ tool, summary, highValue, inFlight }>
  currentToolCallId: null,   // string | null -- in-flight tool for the main agent
  subagent: null,
  pendingInput: null,
  intakeProgress: null,      // IntakeProgressEvent | null -- set during intake phase

  // Client-only state
  notifications: [],
  pipelineEnd: null,
  showSettings: false,
  availableModels: [],
}))

// -- SSE event handlers --

const set = useStore.setState

export function handleInitEvent(d) {
  set({ availableModels: d.availableModels || [] })
}

export function handlePhaseEvent(d) {
  set({
    phase: d.phase,
    // Clear interaction state and intake progress when leaving intake
    ...(d.phase !== 'intake' && { pendingInput: null, intakeProgress: null }),
  })
}

export function handleIntakeProgressEvent(d) {
  set({ intakeProgress: d })
}

export function handleStoriesEvent(d) {
  set({ stories: d.stories })
}

export function handleScoutsEvent(d) {
  set({ scouts: d.scouts })
}

export function handleAgentsEvent(d) {
  set({ agents: d.agents })
}

export function handleLogsEvent(d) {
  set({ logs: d.lines, currentToolCallId: d.currentToolCallId ?? null })
}

export function handleSubagentEvent(d) {
  set({ subagent: d })
}

export function handleSubagentIdleEvent() {
  set({ subagent: null })
}

export function handlePipelineEndEvent(d) {
  set(s => ({
    phase: d.success ? 'completed' : s.phase,
    pipelineEnd: d,
    intakeProgress: null,
  }))
}

export function handleAskEvent(d) {
  set({ pendingInput: { type: 'ask', requestId: d.requestId, payload: d.question } })
}

export function handleReviewEvent(d) {
  set({ pendingInput: { type: 'review', requestId: d.requestId, payload: d.stories } })
}

export function handleModelConfigEvent(d) {
  set(s => ({
    pendingInput: { type: 'model-config', requestId: d.requestId, payload: { ...d.tiers, scoutConcurrency: d.scoutConcurrency } },
    ...(d.availableModels ? { availableModels: d.availableModels } : {}),
  }))
}

export function handleModelConfigConfirmedEvent() {
  set(s => s.pendingInput?.type === 'model-config' ? { pendingInput: null } : {})
}

export function handleAskCancelledEvent(d) {
  set(s => s.pendingInput?.requestId === d.requestId
    ? { pendingInput: null, notifications: [...s.notifications, { id: Date.now(), message: 'The question was cancelled -- the subagent has exited.', level: 'warning' }] }
    : {})
}

export function handleReviewCancelledEvent(d) {
  set(s => s.pendingInput?.requestId === d.requestId
    ? { pendingInput: null, notifications: [...s.notifications, { id: Date.now(), message: 'The review was cancelled.', level: 'warning' }] }
    : {})
}

export function handleNotificationEvent(d) {
  set(s => ({
    notifications: [...s.notifications, { id: Date.now(), message: d.message, level: d.level }],
  }))
}

export function handleConnectionError() {
  set(s => ({
    notifications: [...s.notifications, { id: Date.now(), message: 'Connection lost -- reconnecting...', level: 'warning' }],
  }))
}
