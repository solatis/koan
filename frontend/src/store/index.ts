import { create } from 'zustand'
import { devtools } from 'zustand/middleware'

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

// -- Memory types -- mirrors backend KoanBaseModel.to_wire() camelCase output --

export type MemoryType = 'decision' | 'lesson' | 'context' | 'procedure'

export interface MemoryEntrySummary {
  seq: string
  type: MemoryType
  title: string
  createdMs: number
  modifiedMs: number
}

export interface Proposal {
  id: string
  op: 'add' | 'update' | 'deprecate'
  type: MemoryType
  seq: string
  title: string
  meta: string
  rationale: string
  body?: string
  before?: string
  after?: string
}

export interface ActiveCurationBatch {
  proposals: Proposal[]
  batchId: string
  contextNote: string
}

export interface MemoryState {
  entries: Record<string, MemoryEntrySummary>
  summary: string
}

export interface ReflectCitation {
  id: number
  title: string
}

export interface ReflectTrace {
  iteration: number
  tool: 'search' | 'done'
  query: string
  typeFilter: string
  resultCount: number | null
}

export interface ReflectRun {
  sessionId: string
  question: string
  status: 'in_progress' | 'done' | 'cancelled' | 'failed'
  startedAtMs: number
  completedAtMs: number | null
  iteration: number
  maxIterations: number
  model: string
  traces: ReflectTrace[]
  answer: string
  citations: ReflectCitation[]
  error: string
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

export interface ActiveArtifactReview {
  path: string
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
  activeArtifactReview: ActiveArtifactReview | null  // non-null while orchestrator is blocked in koan_artifact_propose
  activeCurationBatch: ActiveCurationBatch | null  // non-null while orchestrator is blocked in koan_memory_propose
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
  // Project-scoped memory state (not run-scoped; survives workflow boundaries)
  memory: MemoryState
  // Project-scoped reflect state
  reflect: ReflectRun | null

  // Local UI state (not from server)
  settingsOpen: boolean

  // Local draft for chat input — set by YieldPanel row selections
  chatDraft: string

  // Local UI state: currently open artifact review (path or null)
  reviewingArtifact: string | null

  // Store-only curation draft (accept-loss: cleared on memory_curation_cleared).
  // Keyed by proposal id; seeded by resetMemoryCurationDraft on batch mount.
  memoryCurationDraft: Record<string, { decision?: 'approved' | 'rejected'; feedback: string }>
  setMemoryCurationDecision: (id: string, decision: 'approved' | 'rejected' | undefined) => void
  setMemoryCurationFeedback: (id: string, text: string) => void
  resetMemoryCurationDraft: (batch: ActiveCurationBatch | null) => void

  // Store-only memory sidebar state (shared across overview/detail/reflect pages)
  memorySidebar: { search: string; filter: 'all' | MemoryType }
  setMemorySidebarSearch: (v: string) => void
  setMemorySidebarFilter: (v: 'all' | MemoryType) => void

  // Merge memory entries from API fetches without replacing server-patched state
  upsertMemoryEntries: (list: MemoryEntrySummary[]) => void

  // Actions
  setConnected: (v: boolean) => void
  setSettingsOpen: (v: boolean) => void
  setChatDraft: (text: string) => void
  setReviewingArtifact: (path: string | null) => void
}

export const useStore = create<KoanState>()(
  devtools(
    (set) => ({
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
      memory: { entries: {}, summary: '' },
      reflect: null,

      settingsOpen: false,
      chatDraft: '',
      reviewingArtifact: null,
      memoryCurationDraft: {},
      memorySidebar: { search: '', filter: 'all' },

      setMemoryCurationDecision: (id, decision) =>
        set(s => ({
          memoryCurationDraft: {
            ...s.memoryCurationDraft,
            [id]: { ...(s.memoryCurationDraft[id] ?? { feedback: '' }), decision },
          },
        }), false, 'setMemoryCurationDecision'),

      setMemoryCurationFeedback: (id, text) =>
        set(s => ({
          memoryCurationDraft: {
            ...s.memoryCurationDraft,
            [id]: { ...(s.memoryCurationDraft[id] ?? {}), feedback: text },
          },
        }), false, 'setMemoryCurationFeedback'),

      resetMemoryCurationDraft: (batch) => {
        if (batch === null) {
          set({ memoryCurationDraft: {} }, false, 'resetMemoryCurationDraft/clear')
        } else {
          const draft: KoanState['memoryCurationDraft'] = {}
          for (const p of batch.proposals) {
            draft[p.id] = { feedback: '' }
          }
          set({ memoryCurationDraft: draft }, false, 'resetMemoryCurationDraft/seed')
        }
      },

      setMemorySidebarSearch: (v) =>
        set(s => ({ memorySidebar: { ...s.memorySidebar, search: v } }), false, 'setMemorySidebarSearch'),

      setMemorySidebarFilter: (v) =>
        set(s => ({ memorySidebar: { ...s.memorySidebar, filter: v } }), false, 'setMemorySidebarFilter'),

      upsertMemoryEntries: (list) =>
        set(s => {
          const merged = { ...s.memory.entries }
          for (const e of list) {
            merged[e.seq] = e
          }
          return { memory: { ...s.memory, entries: merged } }
        }, false, 'upsertMemoryEntries'),

      setConnected: (v) => set({ connected: v }, false, 'setConnected'),
      setSettingsOpen: (v) => set({ settingsOpen: v }, false, 'setSettingsOpen'),
      setChatDraft: (text) => set({ chatDraft: text }, false, 'setChatDraft'),
      setReviewingArtifact: (path) => set({ reviewingArtifact: path }, false, 'setReviewingArtifact'),
    }),
    {
      name: 'koan',
      // Enabled in Vite dev server (DEV=true) OR when the backend injected
      // <meta name="koan-debug" content="1"> into index.html (which the
      // backend does when started with `uv run koan run --debug`). We read
      // the meta tag inline here rather than via a window flag set from
      // main.tsx, because ES import evaluation happens before main.tsx's
      // body runs — by the time this store module evaluates, the DOM head
      // is already parsed and the meta tag is queryable.
      enabled:
        import.meta.env.DEV ||
        document
          .querySelector('meta[name="koan-debug"]')
          ?.getAttribute('content') === '1',
    },
  ),
)

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
