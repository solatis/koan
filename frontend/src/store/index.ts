import { create } from 'zustand'
import { devtools } from 'zustand/middleware'

// -- Wire types — match backend KoanBaseModel.to_wire() output exactly --------

// Installation interface removed in M4: agent installation concept deleted.
// M5: Profile interface removed -- profiles/default_profile deleted from the backend Settings projection.
// M3: ConnectionStatusInfo removed -- per-connection availability now rides on ConnectionInfo.available.

// ProviderType mirrors route IDs from koan/models/routes.py (anthropic,
// openai, google, bedrock-converse, bedrock-mantle, openrouter, ollama-cloud, voyage) -- not
// provider labels. Both ProviderType definitions (here and ProviderBadge.tsx)
// use route IDs; the modelConfig cast (c.route as ProviderType) is exact.
export type ProviderType = 'google' | 'anthropic' | 'openai' | 'bedrock-converse' | 'bedrock-mantle' | 'openrouter' | 'ollama-cloud' | 'voyage'

/**
 * Wire: ConnectionWire (camelCase via to_camel alias).
 * Non-secret endpoint settings for one provider connection. `route` carries
 * the route ID (e.g. 'bedrock-converse'); `locality` replaces the old `region`
 * (geo-code format); `available` is credential-derived. `base_url` was dropped
 * from the wire in M2 (adapter-internal, not UI-needed).
 */
export interface ConnectionInfo {
  id: string
  route: ProviderType
  locality: string | null
  available: boolean
}

/**
 * Wire: ConfiguredModelWire (camelCase).
 * A (connection, model-id) pair in the global library, carried in the
 * settings_listed full snapshot. `identity` is the resolved ModelIdentity
 * (null when unresolved), `resolved` is whether resolve_offering returned a
 * real identity vs an Unresolved passthrough, and `caps` is the route-aware
 * capability snapshot (base catalog -> route overlay -> profile merge).
 */
export interface ConfiguredModelInfo {
  id: string
  connectionId: string
  modelId: string
  resolvedFrom: string | null
  /** Selected Voyage output dimension; null means use the catalog default. */
  embeddingDim: number | null
  identity: IdentityInfo | null
  resolved: boolean
  caps: CapsInfo
}

/**
 * Wire: IdentityWire (camelCase). Resolved model identity for a configured
 * model or offering -- vendor + family + version lets the frontend derive
 * newest-in-family pins without a separate families payload.
 */
export interface IdentityInfo {
  vendor: string
  family: string
  version: string
  snapshot: string | null
  kind: string
}

/**
 * Wire: CapsWire (camelCase). Route-aware capability snapshot for one
 * configured model or offering. `thinkingLevels` mirrors caps.thinking.modes;
 * `nativeTools` is a sorted list; `provenance` is a per-field dict of
 * {source, date, detail} entries recording where each capability was
 * resolved from (catalog, overlay, or profile).
 */
export interface CapsInfo {
  kind: string
  thinkingLevels: string[]
  promptCaching: string
  nativeTools: string[]
  supportsTools: boolean
  embeddingDims: number[] | null
  resolved: boolean
  provenance: Record<string, { source: string; date: string; detail: string }>
}

/**
 * Wire: OfferingWire (camelCase). One curated catalog entry rendered through
 * a connection's route codec with route-aware caps. `wireId` is the
 * codec-rendered model id for that connection's route; picker content is
 * `offeringsByConnection[connId].map(o => o.wireId)`.
 */
export interface OfferingInfo {
  wireId: string
  identity: IdentityInfo
  displayName: string
  caps: CapsInfo
}

/**
 * Wire: EmbeddingModelWire (camelCase).
 * Static catalog entry for a recognized Voyage embedding model.
 * Populated once at startup via embedding_models_listed; static for process lifetime.
 */
export interface EmbeddingModelInfo {
  modelId: string
  dimensions: number[]
  defaultDimension: number
}

/** Wire: SlotAssignmentWire (camelCase). */
export interface SlotAssignmentInfo {
  configuredModelId: string
  thinking: string
}

/** Wire: PresetWire (camelCase). */
export interface PresetInfo {
  slots: Record<string, SlotAssignmentInfo>
}

// ConnectionStatusInfo deleted in M3: per-connection availability now lives
// on ConnectionInfo.available (settings_listed full snapshot).

// ModelCapabilityInfo deleted in M3: resolved caps now ride on
// ConfiguredModelInfo.caps (settings_listed full snapshot).
/**
 * Wire: memory_bindings dict (opaque snake_case on the wire -- NOT camelCase).
 * Only the embedding key is present; memory_llm and reflect_llm were removed.
 * The thinking field on each binding is now optional (no longer sent by the backend).
 */
export interface MemoryBindingInfo {
  configured_model_id: string
  thinking?: string
}
export type MemoryBindingsInfo = {
  embedding?: MemoryBindingInfo
} | null

// ModelRegistryEntry deleted in M3: the all-providers model catalog is
// replaced by offerings_by_connection (curated catalog rendered per route).

/**
 * Projection Settings -- typed sub-objects use camelCase (to_camel alias);
 * memoryBindings is opaque snake_case on the wire (stored as a raw dict).
 *
 * M3: the five per-field settings surfaces (providerStatus, modelCapabilities,
 * modelRegistry, providerModels, providerFamilies) are replaced by the single
 * settings_listed full-snapshot event. offeringsByConnection is the curated
 * catalog rendered through each available connection's route codec with
 * route-aware caps -- the sole picker-content surface. configuredModels carry
 * identity + resolved + caps so the UI shows resolution status and
 * route-aware capabilities without a separate join.
 */
export interface Settings {
  // installations removed in M4: agent installation concept deleted.
  // M5: profiles/default_profile removed from the backend Settings projection.
  defaultScoutConcurrency: number
  maxRetryAttempts: number
  maxRetryWaitSeconds: number
  workflows: WorkflowInfo[]   // populated once at startup; static for the process lifetime
  connections: ConnectionInfo[]
  configuredModels: ConfiguredModelInfo[]
  presets: Record<string, PresetInfo>
  active: string
  memoryBindings: MemoryBindingsInfo
  /** Curated catalog rendered per available connection's route codec (M3).
   *  Keyed by connection id; picker content is offeringsByConnection[connId]
   *  .map(o => o.wireId). Read defensively as (offeringsByConnection ?? {}):
   *  the SSE snapshot replaces settings wholesale over an untyped boundary
   *  and a missing field reads as undefined, not {}. */
  offeringsByConnection: Record<string, OfferingInfo[]>
  /**
   * Static Voyage embedding model catalog.  Populated once at startup;
   * static for the process lifetime.  Read defensively as (embeddingModels ?? [])
   *  -- the SSE snapshot replaces settings wholesale and a missing field
   *  reads as undefined, not [].
   */
  embeddingModels: EmbeddingModelInfo[]
}

export interface RunConfig {
  // M5: profile removed -- backend renamed to active_preset; not read by any component.
  // installations removed in M4: agent installation concept deleted.
  scoutConcurrency: number
}

// -- ConversationEntry — discriminated union ----------------------------------

// Server-assigned stable key (camelCase wire of entry_id); consumed by virtualization in M4, ignored until then.
// phaseId is the camelCase wire of phase_id, stamped server-side by the fold (_stamp_entry_phases).
export interface ThinkingEntry { type: 'thinking'; content: string; entryId?: string; phaseId?: string }
export interface TextEntry { type: 'text'; text: string; entryId?: string; phaseId?: string }
export interface StepEntry { type: 'step'; step: number; stepName: string; totalSteps: number | null; entryId?: string; phaseId?: string }
export interface UserMessageEntry { type: 'user_message'; content: string; timestampMs: number; entryId?: string; phaseId?: string }

// Mirrors backend AttachmentEntry with Pydantic's to_camel wire format.
export interface AttachmentEntry {
  uploadId: string
  filename: string
  size: number
  contentType: string
  path: string
}

// Placing attachments on BaseToolEntry means all tool-entry variants inherit
// it automatically; the fold sets it only when the event carries a manifest.
// toolInput is the server-side aggregate of all received deltas (M1 fold sets
// it on every tool_input_delta). toolInputDelta is the last-arrived chunk;
// exposed for future highlight-the-just-changed use but not read by M2 consumers.
// entryId: server-assigned stable key; consumed by virtualization in M4, ignored until then.
interface BaseToolEntry {
  callId: string
  inFlight: boolean
  attachments?: AttachmentEntry[] | null
  toolInput?: Record<string, unknown> | null
  toolInputDelta?: Record<string, unknown> | string | null
  // Server-assigned stable key (camelCase wire of entry_id); consumed by virtualization in M4, ignored until then.
  entryId?: string
  // Phase this entry belongs to (camelCase wire of phase_id); inherited by all tool entries.
  phaseId?: string
  // Set by the tool_failed fold for aggregate children: argument validation
  // rejected the call and the tool body never ran. Top-level entries are
  // instead replaced wholesale by ToolFailedEntry.
  failed?: boolean
}
export interface ToolWriteEntry   extends BaseToolEntry { type: 'tool_write';   file: string }
export interface ToolEditEntry    extends BaseToolEntry { type: 'tool_edit';    file: string }
export interface ToolBashEntry    extends BaseToolEntry { type: 'tool_bash';    command: string; startedAtMs: number; completedAtMs: number | null; exitCode: number | null; outputLines: number | null }
export interface ToolGenericEntry extends BaseToolEntry { type: 'tool_generic'; toolName: string; summary: string }
export interface ToolKoanEntry   extends BaseToolEntry { type: 'tool_koan';    toolName: string; args: Record<string, unknown>; result: Record<string, unknown> | null }
// Terminal entry for a call whose arguments failed validation; replaces the
// in-flight entry in the fold. rawInput is the JSON-dumped last-known input --
// an opaque string, never a structured payload.
export interface ToolFailedEntry  extends BaseToolEntry { type: 'tool_failed';  toolName: string; error: string; rawInput?: string }

// Exploration entry types — the six exploration tools (read, grep, glob, bash,
// web_search, web_fetch) are valid both as top-level ConversationEntry values
// (single call -> ToolCallRow family variant) and as ToolAggregateEntry
// children (2+ calls -> ToolAggregateCard).
export interface ToolReadEntry extends BaseToolEntry {
  type: 'tool_read'
  file: string
  startedAtMs: number
  completedAtMs: number | null
  linesRead: number | null
  bytesRead: number | null
  offset: number
  limit: number | null
}
export interface ToolGrepEntry extends BaseToolEntry {
  type: 'tool_grep'
  pattern: string
  startedAtMs: number
  completedAtMs: number | null
  matches: number | null
  filesMatched: number | null
  matchedLines: number | null
}
export interface ToolGlobEntry extends BaseToolEntry {
  type: 'tool_glob'
  pattern: string
  startedAtMs: number
  completedAtMs: number | null
  matches: number | null
  filesMatched: number | null
}
export interface ToolWebSearchEntry extends BaseToolEntry {
  type: 'tool_web_search'
  query: string
  startedAtMs: number
  completedAtMs: number | null
  resultCount: number | null
}
export interface ToolWebFetchEntry extends BaseToolEntry {
  type: 'tool_web_fetch'
  url: string
  startedAtMs: number
  completedAtMs: number | null
  contentSizeBytes: number | null
}
export type ExplorationChild = ToolReadEntry | ToolGrepEntry | ToolGlobEntry | ToolBashEntry | ToolWebSearchEntry | ToolWebFetchEntry

export interface ToolAggregateEntry {
  type: 'tool_aggregate'
  children: ExplorationChild[]
  startedAtMs: number
  // Server-assigned stable key (camelCase wire of entry_id); consumed by virtualization in M4, ignored until then.
  entryId?: string
  phaseId?: string
}

export interface DebugStepGuidanceEntry { type: 'debug_step_guidance'; content: string; entryId?: string; phaseId?: string }
export interface PhaseBoundaryEntry { type: 'phase_boundary'; phase: string; message: string; description: string; entryId?: string; phaseId?: string }

export interface Suggestion { id: string; label: string; command: string; recommended?: boolean; phase?: string }
export interface YieldEntry { type: 'yield'; prompt: string; suggestions: Suggestion[]; entryId?: string; phaseId?: string }

export type ConversationEntry =
  | ThinkingEntry | TextEntry | StepEntry | UserMessageEntry
  | ToolWriteEntry | ToolEditEntry | ToolBashEntry | ToolGenericEntry
  | ToolKoanEntry | ToolFailedEntry | ToolAggregateEntry
  | ToolReadEntry | ToolGrepEntry | ToolGlobEntry | ToolWebSearchEntry | ToolWebFetchEntry
  | DebugStepGuidanceEntry | PhaseBoundaryEntry | YieldEntry

export interface Conversation {
  entries: ConversationEntry[]
  pendingThinking: string
  pendingText: string
  isThinking: boolean
  inputTokens: number
  outputTokens: number
  cacheReadTokens: number
  cacheWriteTokens: number
  totalCostUsd: number
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

// Proposal and ActiveCurationBatch interfaces removed in M7: the
// koan_memory_propose approval gate is retired; curation writes memory directly.

export interface MemoryState {
  entries: Record<string, MemoryEntrySummary>
  summary: string
}

export interface ReflectCitation {
  id: number
  title: string
  type: MemoryType
  modifiedMs: number
}

export interface ReflectTrace {
  iteration: number
  kind: 'search' | 'done' | 'thinking' | 'text'
  query: string
  typeFilter: string
  resultCount: number | null
  delta: string
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
  producedPhaseId?: string   // phase that created the artifact (stamped server-side by the fold)
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

// -- Client-only toast channel ------------------------------------------------

/**
 * Client-only toast, not projection-synced.  Survives the SSE merge (same
 * as chatDraft/lastCompletion) because connect.ts only merges SSE-projected
 * state, not the full store object.
 */
export interface ClientToast {
  id: number
  message: string
  level: 'info' | 'warning' | 'error'
}

// -- Run ----------------------------------------------------------------------

export interface SteeringMessage {
  content: string
  timestampMs?: number
}

export interface Suggestion {
  id: string
  label: string
  command: string
  /** Non-empty marks a mechanical phase-transition suggestion routed to POST /api/phase; empty/absent means free-text (chat-draft path). */
  phase?: string
}

export interface ActiveYield {
  suggestions: Suggestion[]
}

// ActiveArtifactReview removed in M6 -- koan_artifact_propose deleted in M5;
// the backend no longer emits artifact_review_started events.

export interface PhaseInfo {
  id: string
  description: string
}

export interface WorkflowInfo {
  id: string
  description: string
  phases: PhaseInfo[]
  initialPhase: string
}

export interface Run {
  config: RunConfig
  phase: string
  workflow: string    // active workflow name
  availablePhases: PhaseInfo[]      // populated on workflow_selected; drives the / command palette
  // availableWorkflows removed: the workflows registry now lives at settings.workflows (populated by the workflows_listed initial event).
  agents: Record<string, Agent>
  focus: Focus | null
  artifacts: Record<string, ArtifactInfo>
  completion: CompletionInfo | null
  steering: SteeringMessage[]
  activeYield: ActiveYield | null  // non-null while orchestrator is blocked in koan_yield
  // activeCurationBatch removed in M7: koan_memory_propose gate retired.
}

// -- Store --------------------------------------------------------------------

export interface KoanState {
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

  // Client-only toast channel (not projection-synced; survives SSE merge).
  // Use pushToast for revert-on-reject error messages and other transient notices.
  toasts: ClientToast[]
  /** Append a new toast; id is auto-assigned. */
  pushToast: (message: string, level: 'info' | 'warning' | 'error') => void
  /** Remove a toast by its auto-assigned id. */
  dismissToast: (id: number) => void

  // Ephemeral snapshot of the last run's completion — populated on the null->non-null
  // rising edge of run.completion and cleared by the user (dismiss button) or a new run.
  // Not persisted; not mirrored in the projection. UI-only.
  lastCompletion: CompletionInfo | null
  setLastCompletion: (c: CompletionInfo | null) => void

  // Local draft for chat input — set by YieldPanel row selections
  chatDraft: string

  // Local UI state: currently open artifact review (path or null)
  reviewingArtifact: string | null

  // Local UI state: which phase's entries are shown in the content stream.
  // null — follow the active phase (live mode; filters to run.phase).
  // non-null string — view a specific historical phase's entries.
  viewingPhaseId: string | null

  // Timestamp of the last yield resolution (suggestion clicked / chat submitted).
  // Null until the first yield resolves; all artifacts show as "changed" until then.
  // Updated client-side on send; not persisted or mirrored in SSE projection.
  lastTouchpointMs: number | null
  setLastTouchpointMs: (ms: number) => void

  // memoryCurationDraft and its setters removed in M7: koan_memory_propose
  // gate retired; no per-proposal decision/feedback draft state needed.

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
  setViewingPhaseId: (id: string | null) => void
}

export const useStore = create<KoanState>()(
  devtools(
    (set) => ({
      connected: false,
      lastVersion: 0,

      settings: {
        // installations removed in M4: agent installation concept deleted.
        // M5: profiles/defaultProfile init values removed.
        defaultScoutConcurrency: 8,
        maxRetryAttempts: 10,
        maxRetryWaitSeconds: 60,
        workflows: [],
        connections: [],
        configuredModels: [],
        presets: {},
        active: '$last',
        memoryBindings: null,
        offeringsByConnection: {},
        embeddingModels: [],
      },
      run: null,
      notifications: [],
      memory: { entries: {}, summary: '' },
      reflect: null,

      settingsOpen: false,
      toasts: [],
      lastCompletion: null,
      chatDraft: '',
      reviewingArtifact: null,
      viewingPhaseId: null,
      lastTouchpointMs: null,
      // memoryCurationDraft initial value removed in M7: koan_memory_propose retired.
      memorySidebar: { search: '', filter: 'all' },

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

      pushToast: (message, level) =>
        set(s => ({
          // Use Date.now() + random to avoid collisions on rapid-fire toasts.
          toasts: [...s.toasts, { id: Date.now() + Math.random(), message, level }],
        }), false, 'pushToast'),

      dismissToast: (id) =>
        set(s => ({ toasts: s.toasts.filter(t => t.id !== id) }), false, 'dismissToast'),

      setConnected: (v) => set({ connected: v }, false, 'setConnected'),
      setSettingsOpen: (v) => set({ settingsOpen: v }, false, 'setSettingsOpen'),
      setLastCompletion: (c) => set({ lastCompletion: c }, false, 'setLastCompletion'),
      setChatDraft: (text) => set({ chatDraft: text }, false, 'setChatDraft'),
      setReviewingArtifact: (path) => set({ reviewingArtifact: path }, false, 'setReviewingArtifact'),
      setViewingPhaseId: (id) => set({ viewingPhaseId: id }, false, 'setViewingPhaseId'),
      setLastTouchpointMs: (ms) => set({ lastTouchpointMs: ms }, false, 'setLastTouchpointMs'),
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

// Final 8-phase set (brief 5.4, M6 cutover). The *-review phases are removed:
// plan-review, milestone-review, tech-plan-review, exec-review are collapsed
// into the mechanical reviewer sub-agent (M3) and inline execute review (M5).
// Ghost phases (brief-generation, ticket-breakdown, cross-artifact-validation,
// execution, implementation-validation) were removed in M1.
export const ALL_PHASES = [
  'intake', 'core-flows',
  'tech-plan',
  'milestone',
  'plan',
  'execute',
  'curation', 'frame',
]
