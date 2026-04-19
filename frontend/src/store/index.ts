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
export interface UserMessageEntry { type: 'user_message'; content: string; timestampMs: number }

interface BaseToolEntry { callId: string; inFlight: boolean }
export interface ToolWriteEntry   extends BaseToolEntry { type: 'tool_write';   file: string }
export interface ToolEditEntry    extends BaseToolEntry { type: 'tool_edit';    file: string }
export interface ToolBashEntry    extends BaseToolEntry { type: 'tool_bash';    command: string }
export interface ToolGenericEntry extends BaseToolEntry { type: 'tool_generic'; toolName: string; summary: string }

// Aggregate children — exploration tools (read/grep/ls) never appear as
// top-level ConversationEntry values. They live only inside ToolAggregateEntry.
export interface AggregateReadChild extends BaseToolEntry {
  tool: 'read'
  file: string
  lines: string
  startedAtMs: number
  completedAtMs: number | null
  linesRead: number | null
  bytesRead: number | null
}
export interface AggregateGrepChild extends BaseToolEntry {
  tool: 'grep'
  pattern: string
  startedAtMs: number
  completedAtMs: number | null
  matches: number | null
  filesMatched: number | null
}
export interface AggregateLsChild extends BaseToolEntry {
  tool: 'ls'
  path: string
  startedAtMs: number
  completedAtMs: number | null
  entries: number | null
  directories: number | null
}
export type AggregateChild = AggregateReadChild | AggregateGrepChild | AggregateLsChild

export interface ToolAggregateEntry {
  type: 'tool_aggregate'
  children: AggregateChild[]
  startedAtMs: number
}

export interface DebugStepGuidanceEntry { type: 'debug_step_guidance'; content: string }
export interface PhaseBoundaryEntry { type: 'phase_boundary'; phase: string; message: string; description: string }

export interface Suggestion { id: string; label: string; command: string; recommended?: boolean }
export interface YieldEntry { type: 'yield'; prompt: string; suggestions: Suggestion[] }

export type ConversationEntry =
  | ThinkingEntry | TextEntry | StepEntry | UserMessageEntry
  | ToolWriteEntry | ToolEditEntry | ToolBashEntry | ToolGenericEntry
  | ToolAggregateEntry
  | DebugStepGuidanceEntry | PhaseBoundaryEntry | YieldEntry

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
  completedAtMs: number | null
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
  free_text?: boolean     // when true (or when options is empty), render a textarea instead of options
}

export interface ConversationFocus { type: 'conversation'; agentId: string }
export interface QuestionFocus     { type: 'question';     agentId: string; token: string; questions: AskQuestion[] }

export type Focus = ConversationFocus | QuestionFocus

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

export interface SteeringMessage {
  content: string
}

export interface Suggestion {
  id: string
  label: string
  command: string
}

export interface ActiveYield {
  suggestions: Suggestion[]
}

export interface PhaseInfo {
  id: string
  description: string
}

export interface Run {
  config: RunConfig
  phase: string
  workflow: string    // active workflow name
  availablePhases: PhaseInfo[]  // populated on workflow_selected; drives the / command palette
  agents: Record<string, Agent>
  focus: Focus | null
  artifacts: Record<string, ArtifactInfo>
  completion: CompletionInfo | null
  steering: SteeringMessage[]
  activeYield: ActiveYield | null  // non-null while orchestrator is blocked in koan_yield
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

  // Local draft for chat input — set by YieldPanel row selections
  chatDraft: string

  // Local UI state: currently open artifact review (path or null)
  reviewingArtifact: string | null

  // Actions
  setConnected: (v: boolean) => void
  setSettingsOpen: (v: boolean) => void
  setChatDraft: (text: string) => void
  setReviewingArtifact: (path: string | null) => void
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
  chatDraft: '',
  reviewingArtifact: null,

  setConnected: (v) => set({ connected: v }),
  setSettingsOpen: (v) => set({ settingsOpen: v }),
  setChatDraft: (text) => set({ chatDraft: text }),
  setReviewingArtifact: (path) => set({ reviewingArtifact: path }),
}))

export type KoanStore = typeof useStore

// -- ALL_PHASES (frontend-only derivation helper) ----------------------------

export const ALL_PHASES = [
  // Legacy workflow phases
  'intake', 'brief-generation', 'core-flows', 'tech-plan',
  'ticket-breakdown', 'cross-artifact-validation',
  'execution', 'implementation-validation',
  // Plan workflow phases
  'plan-spec', 'plan-review', 'execute',
]
