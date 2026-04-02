import { create } from 'zustand'

// -- Wire types — match backend KoanBaseModel.to_wire() output exactly --------

export interface Installation {
  alias: string
  runnerType: string
  binary: string
  extraArgs: string[]
  available: boolean
}

export interface Profile {
  name: string
  readOnly: boolean
  tiers: Record<string, string>   // role → installation alias
}

export interface Settings {
  installations: Record<string, Installation>
  profiles: Record<string, Profile>
  defaultProfile: string
  defaultScoutConcurrency: number
}

export interface RunConfig {
  profile: string
  installations: Record<string, string>  // role → installation alias
  scoutConcurrency: number
}

// -- ConversationEntry — discriminated union ----------------------------------

export interface ThinkingEntry { type: 'thinking'; content: string }
export interface TextEntry { type: 'text'; text: string }
export interface StepEntry { type: 'step'; step: number; stepName: string; totalSteps: number | null }

interface BaseToolEntry { callId: string; inFlight: boolean }
export interface ToolReadEntry    extends BaseToolEntry { type: 'tool_read';    file: string; lines: string }
export interface ToolWriteEntry   extends BaseToolEntry { type: 'tool_write';   file: string }
export interface ToolEditEntry    extends BaseToolEntry { type: 'tool_edit';    file: string }
export interface ToolBashEntry    extends BaseToolEntry { type: 'tool_bash';    command: string }
export interface ToolGrepEntry    extends BaseToolEntry { type: 'tool_grep';    pattern: string }
export interface ToolLsEntry      extends BaseToolEntry { type: 'tool_ls';      path: string }
export interface ToolGenericEntry extends BaseToolEntry { type: 'tool_generic'; toolName: string; summary: string }
export interface DebugStepGuidanceEntry { type: 'debug_step_guidance'; content: string }

export type ConversationEntry =
  | ThinkingEntry | TextEntry | StepEntry
  | ToolReadEntry | ToolWriteEntry | ToolEditEntry
  | ToolBashEntry | ToolGrepEntry | ToolLsEntry | ToolGenericEntry
  | DebugStepGuidanceEntry

export interface Conversation {
  entries: ConversationEntry[]
  pendingThinking: string
  pendingText: string
  isThinking: boolean
  inputTokens: number
  outputTokens: number
}

// -- Agent --------------------------------------------------------------------

export type AgentStatus = 'queued' | 'running' | 'done' | 'failed'

export interface Agent {
  agentId: string
  role: string
  label: string
  model: string | null
  isPrimary: boolean
  status: AgentStatus
  error: string | null
  startedAtMs: number
  step: number
  stepName: string
  lastTool: string
  conversation: Conversation
}

// -- Focus — discriminated union ----------------------------------------------

export interface AskQuestion {
  question: string
  multi: boolean
  options: { value: string; label: string; recommended?: boolean }[]
  allow_other?: boolean   // snake_case: comes from LLM via backend list[dict]
  context?: string
}

export interface ChatTurn {
  role: 'orchestrator' | 'user'
  status_report?: string              // snake_case from backend list[dict]
  recommended_phases?: { phase: string; context?: string; recommended?: boolean }[]
  message?: string
}

export interface ConversationFocus { type: 'conversation'; agentId: string }
export interface QuestionFocus     { type: 'question';     agentId: string; token: string; questions: AskQuestion[] }
export interface ReviewFocus       { type: 'review';       agentId: string; token: string; path: string; description: string; content: string }
export interface DecisionFocus     { type: 'decision';     agentId: string; token: string; chatTurns: ChatTurn[] }

export type Focus = ConversationFocus | QuestionFocus | ReviewFocus | DecisionFocus

// -- Supporting types ---------------------------------------------------------

export interface ArtifactInfo {
  path: string
  size: number
  modifiedAt: number   // ms since epoch
}

export interface CompletionInfo {
  success: boolean
  summary: string
  error?: string | null
}

export interface Notification {
  message: string
  level: 'info' | 'warning' | 'error'
  timestampMs: number
}

// -- Run ----------------------------------------------------------------------

export interface Run {
  config: RunConfig
  phase: string
  agents: Record<string, Agent>
  focus: Focus | null
  artifacts: Record<string, ArtifactInfo>
  completion: CompletionInfo | null
}

// -- Store --------------------------------------------------------------------

interface KoanState {
  // Connection
  connected: boolean
  lastVersion: number

  // Projection state — mirrors server wire format; patches apply directly
  settings: Settings
  run: Run | null
  notifications: Notification[]

  // Local UI state (not from server)
  settingsOpen: boolean

  // Actions
  setConnected: (v: boolean) => void
  setSettingsOpen: (v: boolean) => void
}

export const useStore = create<KoanState>((set) => ({
  connected: false,
  lastVersion: 0,

  settings: {
    installations: {},
    profiles: {},
    defaultProfile: 'balanced',
    defaultScoutConcurrency: 8,
  },
  run: null,
  notifications: [],

  settingsOpen: false,

  setConnected: (v) => set({ connected: v }),
  setSettingsOpen: (v) => set({ settingsOpen: v }),
}))

export type KoanStore = typeof useStore

// -- ALL_PHASES (frontend-only derivation helper) ----------------------------

export const ALL_PHASES = [
  'intake', 'brief-generation', 'core-flows', 'tech-plan',
  'ticket-breakdown', 'cross-artifact-validation',
  'execution', 'implementation-validation',
]
