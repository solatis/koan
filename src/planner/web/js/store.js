import { create } from 'zustand'

export const useStore = create((set) => ({
  // Server-pushed state
  phase: null,
  stories: [],
  scouts: [],
  agents: [],
  logs: [],                  // Array<{ tool, summary, highValue, inFlight }>
  currentToolCallId: null,   // string | null — in-flight tool for the main agent
  subagent: null,
  pendingInput: null,

  // Client-only state
  notifications: [],
  pipelineEnd: null,
  showSettings: false,
  availableModels: [],
}))
