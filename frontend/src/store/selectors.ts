import { useMemo } from 'react'
import { createSelector } from 'reselect'
import { useStore, KoanState, ArtifactInfo, ConversationEntry,
         Conversation, SteeringMessage, Agent, Focus, CompletionInfo,
         MemoryEntrySummary, MemoryType, ReflectRun, ActiveCurationBatch,
         Notification, ClientToast } from './index'

// ---------------------------------------------------------------------------
// Artifact tree selector (pre-existing)
// ---------------------------------------------------------------------------

// Derive artifact tree grouped by directory
function groupByDirectory(artifacts: ArtifactInfo[]): Record<string, ArtifactInfo[]> {
  const tree: Record<string, ArtifactInfo[]> = {}
  for (const a of artifacts) {
    const parts = a.path.split('/')
    const dir = parts.length > 1 ? parts.slice(0, -1).join('/') : 'run-root'
    if (!tree[dir]) tree[dir] = []
    tree[dir].push(a)
  }
  return tree
}

// Subscribe to run.artifacts -- derive the tree in useMemo to avoid recreating
// the array on every render (which would trigger useSyncExternalStore loops).
export function useArtifactTree() {
  const artifacts = useStore(s => s.run?.artifacts ?? {})
  return useMemo(() => groupByDirectory(Object.values(artifacts)), [artifacts])
}

// ---------------------------------------------------------------------------
// Stable empty constants
//
// useSyncExternalStore compares selector return values with Object.is(). A
// fresh [] or {} on every call is never === the previous one, causing a
// spurious re-render even when nothing changed. Module-level const arrays
// return the SAME reference every time the slice is absent -- they are not
// mutated anywhere (the store always replaces, never pushes into these).
// ---------------------------------------------------------------------------

const EMPTY_ENTRIES: ConversationEntry[] = []
const EMPTY_STEERING: SteeringMessage[] = []
const EMPTY_PHASES: { id: string; description: string }[] = []
// Run-view stable empty constants (same rationale as above: stable references
// prevent spurious re-renders when the run is absent or a slice is empty).
const EMPTY_ARTIFACTS: Record<string, ArtifactInfo> = {}
const EMPTY_AGENTS: Record<string, Agent> = {}

// ---------------------------------------------------------------------------
// Layer-1 helpers: narrow raw slice accessors (not exported; composed below)
// ---------------------------------------------------------------------------

// Navigate to the focused agent's conversation without exposing the whole run.
// Returns undefined when there is no run or no focused agent, keeping callers
// from accidentally depending on the run reference itself (which changes on
// every patch due to copy-on-write along the root->run->...->pendingText path).
function focusedConversation(s: KoanState): Conversation | undefined {
  const id = s.run?.focus?.agentId
  return id ? s.run?.agents?.[id]?.conversation : undefined
}

// ---------------------------------------------------------------------------
// Layer-2 exported leaf selectors
//
// Each returns a primitive or a stable reference (the EMPTY constants above).
// No selector here subscribes to s.run or s.run.agents by reference.
// ---------------------------------------------------------------------------

/**
 * The committed conversation entries for the focused agent.
 * Returns EMPTY_ENTRIES (same reference) when there is no focused conversation,
 * so CommittedList does not re-render when there is no active run.
 */
export const selectFocusedEntries = (s: KoanState): ConversationEntry[] =>
  focusedConversation(s)?.entries ?? EMPTY_ENTRIES

/**
 * The raw pending-thinking text (empty string when absent).
 * Only StreamingLeaf subscribes to this; it is the sole component that
 * re-renders on every thinking token.
 */
export const selectPendingThinking = (s: KoanState): string =>
  focusedConversation(s)?.pendingThinking ?? ''

/**
 * The raw pending-answer text (empty string when absent).
 * Only StreamingLeaf subscribes to this; it is the sole component that
 * re-renders on every text token.
 */
export const selectPendingText = (s: KoanState): string =>
  focusedConversation(s)?.pendingText ?? ''

/**
 * Whether the agent is currently in a thinking turn.
 * Boolean primitive -- stable across unrelated patches.
 */
export const selectIsThinking = (s: KoanState): boolean =>
  focusedConversation(s)?.isThinking ?? false

/**
 * Whether the feedback input and steering bar should be shown.
 * True when there is an active run with no non-conversation focus (question, etc.).
 */
export const selectShowFeedback = (s: KoanState): boolean =>
  s.run != null && (s.run.focus == null || s.run.focus.type === 'conversation')

/**
 * The steering message list for the active run.
 * Returns EMPTY_STEERING (same reference) when absent so SteeringBar
 * does not re-render on unrelated patches.
 */
export const selectSteering = (s: KoanState): SteeringMessage[] =>
  s.run?.steering ?? EMPTY_STEERING

/**
 * Whether there is a completion record on the run.
 * Used to disable the feedback input after the run finishes.
 */
export const selectCompletionPresent = (s: KoanState): boolean =>
  s.run?.completion != null

// ---------------------------------------------------------------------------
// Run-view leaf selectors
//
// These serve the run-view connected wrappers (ConnectedSidebar,
// ConnectedScoutBar, ElicitationView, CompletionView, ReviewView,
// useHeaderData). Each returns a primitive or a stable EMPTY_* reference.
// Selectors deriving time-relative display strings (e.g. elapsed) are NOT
// defined here -- they stay as in-component useMemo with Date.now().
// ---------------------------------------------------------------------------

/**
 * The artifacts map for the active run.
 * Returns EMPTY_ARTIFACTS (same reference) when there is no active run,
 * so consumers do not re-render on unrelated patches.
 */
export const selectArtifacts = (s: KoanState): Record<string, ArtifactInfo> =>
  s.run?.artifacts ?? EMPTY_ARTIFACTS

/**
 * The agents map for the active run.
 * Returns EMPTY_AGENTS (same reference) when there is no active run.
 * Referentially stable across patches that do not touch agents.
 */
export const selectAgents = (s: KoanState): Record<string, Agent> =>
  s.run?.agents ?? EMPTY_AGENTS

/**
 * The current focus for the active run (question or conversation).
 * Null when there is no active run or no focus is set.
 */
export const selectFocus = (s: KoanState): Focus | null =>
  s.run?.focus ?? null

/**
 * The completion record for the active run.
 * Null until the run completes (success or failure).
 */
export const selectCompletion = (s: KoanState): CompletionInfo | null =>
  s.run?.completion ?? null

/**
 * The active phase string for the current run (e.g. 'plan-spec').
 * Empty string when there is no active run.
 */
export const selectPhase = (s: KoanState): string =>
  s.run?.phase ?? ''

/**
 * The path of the artifact currently open in the review panel.
 * Null when no artifact is being reviewed.
 */
export const selectReviewingArtifact = (s: KoanState): string | null =>
  s.reviewingArtifact

/**
 * Timestamp (ms since epoch) of the last yield resolution.
 * Null until the user first submits a yield answer.
 * Used to mark artifacts as "changed since last interaction".
 */
export const selectLastTouchpointMs = (s: KoanState): number | null =>
  s.lastTouchpointMs

// ---------------------------------------------------------------------------
// Derived run-view selector
// ---------------------------------------------------------------------------

/**
 * The primary (orchestrator) agent for the active run.
 * Null when there is no active run or no primary agent is present.
 * Memoized via reselect: re-derives only when selectAgents output changes,
 * so useHeaderData does not re-render on patches that do not touch agents.
 */
export const selectPrimaryAgent = createSelector(
  [selectAgents],
  (agents): Agent | null => Object.values(agents).find(a => a.isPrimary) ?? null,
)

// ---------------------------------------------------------------------------
// Layer-2 private inputs for the derived command selector
// ---------------------------------------------------------------------------

const selectActiveYieldPresent = (s: KoanState): boolean => s.run?.activeYield != null
const selectAvailablePhases = (s: KoanState): { id: string; description: string }[] =>
  s.run?.availablePhases ?? EMPTY_PHASES
const selectWorkflows = (s: KoanState) => s.settings.workflows

// ---------------------------------------------------------------------------
// Layer-3 derived selector
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Memory / curation / notification leaf selectors
//
// These serve MemoryRoutes connected wrappers, CurationTakeover, Notification,
// and FeedbackInput. Each returns a primitive or a stable slice reference.
// Structural sharing (M2 Immer applicator) keeps these references stable
// across patches that do not touch the slice.
// ---------------------------------------------------------------------------

/**
 * All memory entry summaries keyed by seq.
 * Referentially stable across patches that do not touch memory.entries.
 */
export const selectMemoryEntries = (s: KoanState): Record<string, MemoryEntrySummary> =>
  s.memory.entries

/**
 * The prose summary of the memory corpus (empty string when absent).
 * A string primitive -- always stable.
 */
export const selectMemorySummary = (s: KoanState): string =>
  s.memory.summary

/**
 * The shared memory sidebar state (search query + type filter).
 * Referentially stable across patches that do not touch memorySidebar.
 */
export const selectMemorySidebar = (s: KoanState): { search: string; filter: 'all' | MemoryType } =>
  s.memorySidebar

/**
 * The active reflect session (null when no reflect is running or complete).
 * Referentially stable across patches that do not touch reflect.
 */
export const selectReflect = (s: KoanState): ReflectRun | null =>
  s.reflect

/**
 * The active curation batch proposed by koan_memory_propose.
 * Returns null when there is no active run or no batch is pending.
 * Uses `?? null` rather than `?? undefined` so the return type is a stable
 * literal (Object.is(null, null) === true) when the run is absent.
 */
export const selectActiveCurationBatch = (s: KoanState): ActiveCurationBatch | null =>
  s.run?.activeCurationBatch ?? null

/**
 * Per-proposal decision/feedback draft for the current curation batch.
 * Keyed by proposal id; seeded by resetMemoryCurationDraft on batch mount.
 * Referentially stable across patches that do not touch memoryCurationDraft.
 */
export const selectMemoryCurationDraft = (
  s: KoanState
): Record<string, { decision?: 'approved' | 'rejected'; feedback: string }> =>
  s.memoryCurationDraft

/**
 * Server-synced notification list (append-only from projection patches).
 * Referentially stable across patches that do not touch notifications.
 */
export const selectNotifications = (s: KoanState): Notification[] =>
  s.notifications

/**
 * Client-only toast list (dismissed via dismissToast; not SSE-backed).
 * Referentially stable across patches that do not touch toasts.
 */
export const selectToasts = (s: KoanState): ClientToast[] =>
  s.toasts

/**
 * The command palette pre-fill draft text (cleared after consumption).
 * String primitive -- always stable.
 */
export const selectChatDraft = (s: KoanState): string =>
  s.chatDraft

/**
 * The slash-command list shown in the FeedbackInput command palette.
 * Returns undefined (palette hidden) when there is no active yield; returns a
 * memoized array of phase and workflow commands when the orchestrator is
 * blocked in koan_yield. createSelector memoizes the result so the array
 * reference is stable when inputs have not changed.
 */
export const selectFeedbackCommands = createSelector(
  [selectActiveYieldPresent, selectAvailablePhases, selectWorkflows],
  (hasYield, phases, workflows) =>
    hasYield
      ? [
          ...phases,
          // Workflow commands use "workflow:<name>" IDs (colon, not space)
          // so the palette startsWith filter works and no space breaks the
          // paletteOpen guard in FeedbackInput.
          ...workflows.map(w => ({
            id: `workflow:${w.id}`,
            description: `Switch to ${w.id} workflow${w.description ? ` -- ${w.description}` : ''}`,
          })),
        ]
      : undefined,
)
