import { create } from 'zustand'
import type { RunnerInfo } from '../api/client'

export const ALL_PHASES = [
  'intake', 'brief-generation', 'core-flows', 'tech-plan',
  'ticket-breakdown', 'cross-artifact-validation',
  'execution', 'implementation-validation',
]

// -- Domain types ------------------------------------------------------------

export interface AgentInfo {
  agentId: string
  role: string
  model: string | null
  step: number
  stepName: string
  startedAt: number   // UTC epoch milliseconds
  tokensSent: number
  tokensReceived: number
}

export interface ArtifactFile {
  path: string
  size: number
  modifiedAt: number  // UTC epoch milliseconds
}

export interface CompletionInfo {
  success: boolean
  summary: string
  error?: string
  phase?: string
}

export interface NotificationEntry {
  id: string
  type: string
  severity: 'error' | 'warning' | 'info'
  message: string
  detail?: string
}

export interface ActivityEntry {
  tool: string
  summary: string
  inFlight: boolean
  callId?: string
  ts?: string
}

export interface AskOption {
  value: string
  label: string
  recommended?: boolean
}

export interface AskQuestion {
  question: string
  multi: boolean
  options: AskOption[]
  allow_other?: boolean
  context?: string
}

export interface ChatTurn {
  role: 'orchestrator' | 'user'
  status_report?: string
  recommended_phases?: { phase: string; context?: string; recommended?: boolean }[]
  message?: string
}

export type Interaction =
  | { type: 'ask'; questions: AskQuestion[]; token: string }
  | { type: 'artifact-review'; content: string; description?: string; path?: string; token: string }
  | { type: 'workflow-decision'; chat_turns: ChatTurn[]; token: string }

export interface ProfileTierConfig {
  runner_type: string
  model: string
  thinking: string
}

export interface Profile {
  name: string
  read_only: boolean
  tiers: Record<string, ProfileTierConfig>
}

export interface Installation {
  alias: string
  runner_type: string
  binary: string
  extra_args: string[]
  is_active?: boolean
}

// Severity mapping for notification-worthy event types
const SEVERITY_MAP: Record<string, 'error' | 'warning' | 'info'> = {
  agent_spawn_failed: 'error',
  agent_exited_error: 'error',
}

// Map backend interaction_type event strings to frontend Interaction.type values
function interactionTypeToFrontend(interactionType: string): string {
  switch (interactionType) {
    case 'questions_asked': return 'ask'
    case 'artifact_review_requested': return 'artifact-review'
    case 'workflow_decision_requested': return 'workflow-decision'
    default: return interactionType
  }
}

function transformAgent(a: Record<string, unknown>): AgentInfo {
  return {
    agentId:        a['agent_id'] as string,
    role:           a['role'] as string,
    model:          a['model'] as string | null,
    step:           (a['step'] as number) ?? 0,
    stepName:       (a['step_name'] as string) ?? '',
    startedAt:      (a['started_at_ms'] as number) ?? 0,
    tokensSent:     (a['input_tokens'] as number) ?? 0,
    tokensReceived: (a['output_tokens'] as number) ?? 0,
  }
}

function transformArtifact(a: Record<string, unknown>): ArtifactFile {
  return {
    path:       a['path'] as string,
    size:       (a['size'] as number) ?? 0,
    modifiedAt: (a['modified_at'] as number) ?? 0,
  }
}

// -- Store -------------------------------------------------------------------

interface KoanState {
  // Connection
  connected: boolean
  lastVersion: number
  fatalError: boolean

  // Run state
  runStarted: boolean
  phase: string
  donePhases: string[]

  // Primary agent (phase-level)
  primaryAgent: AgentInfo | null

  // Completed agents (exited, token totals preserved)
  completedAgents: AgentInfo[]

  // Intake sub-phase progress (legacy, kept for compatibility)
  intakeProgress: { subPhase: string; confidence: string | null; summary: string } | null

  // Scout agents — keyed by agentId
  scouts: Record<string, AgentInfo>

  // Activity feed
  activityLog: ActivityEntry[]
  streamBuffer: string
  isThinking: boolean

  // Notifications
  notifications: NotificationEntry[]

  // Active interaction (at most one at a time)
  activeInteraction: Interaction | null

  // Artifacts — keyed by path
  artifacts: Record<string, ArtifactFile>

  // Workflow completion
  completion: CompletionInfo | null

  // Settings
  settingsOpen: boolean
  profiles: Profile[]
  installations: Installation[]

  // Configuration — sourced from projection events, always up to date
  configProfiles: Profile[]
  configInstallations: Installation[]
  configActiveProfile: string
  configScoutConcurrency: number
  configRunners: RunnerInfo[]

  // Legacy actions (used by existing components)
  setConnected: (v: boolean) => void
  setPhase: (phase: string) => void
  setPrimaryAgent: (agent: AgentInfo | null) => void
  setIntakeProgress: (p: KoanState['intakeProgress']) => void
  setScouts: (scouts: Record<string, AgentInfo>) => void
  appendLog: (entry: ActivityEntry) => void
  completeLog: (callId: string) => void
  appendStreamDelta: (delta: string) => void
  clearStream: () => void
  addNotification: (n: NotificationEntry) => void
  dismissNotification: (id: string) => void
  setInteraction: (interaction: Interaction | null) => void
  setArtifacts: (artifacts: Record<string, ArtifactFile>) => void
  setCompletion: (info: CompletionInfo) => void
  setSettingsOpen: (v: boolean) => void
  setProfiles: (profiles: Profile[]) => void
  setInstallations: (installations: Installation[]) => void
  setFatalError: (v: boolean) => void

  // Event-sourced actions
  applySnapshot: (data: Record<string, unknown>) => void
  applyEvent: (event: Record<string, unknown>) => void
}

export const useStore = create<KoanState>((set) => ({
  connected: false,
  lastVersion: 0,
  fatalError: false,
  runStarted: false,
  phase: '',
  donePhases: [],
  primaryAgent: null,
  completedAgents: [],
  intakeProgress: null,
  scouts: {},
  activityLog: [],
  streamBuffer: '',
  isThinking: false,
  notifications: [],
  activeInteraction: null,
  artifacts: {},
  completion: null,
  settingsOpen: false,
  profiles: [],
  installations: [],

  // Configuration defaults
  configProfiles: [],
  configInstallations: [],
  configActiveProfile: 'balanced',
  configScoutConcurrency: 8,
  configRunners: [],

  setConnected: (v) => set({ connected: v }),
  setFatalError: (v) => set({ fatalError: v }),

  setPhase: (phase) => set(() => {
    const idx = ALL_PHASES.indexOf(phase)
    const donePhases = idx === -1 ? [...ALL_PHASES] : ALL_PHASES.slice(0, idx)
    return { phase, runStarted: true, donePhases }
  }),

  setPrimaryAgent: (agent) => set({ primaryAgent: agent }),
  setIntakeProgress: (p) => set({ intakeProgress: p }),
  setScouts: (scouts) => set({ scouts }),
  appendLog: (entry) => set((s) => ({ activityLog: [...s.activityLog, entry] })),
  completeLog: (callId) => set((s) => ({
    activityLog: s.activityLog.map(e =>
      e.callId === callId ? { ...e, inFlight: false } : e
    ),
  })),
  appendStreamDelta: (delta) => set((s) => ({ streamBuffer: s.streamBuffer + delta })),
  clearStream: () => set({ streamBuffer: '' }),
  addNotification: (n) => set((s) => ({ notifications: [...s.notifications, n] })),
  dismissNotification: (id) => set((s) => ({
    notifications: s.notifications.filter((n) => n.id !== id),
  })),
  setInteraction: (interaction) => set({ activeInteraction: interaction }),
  setArtifacts: (artifacts) => set({ artifacts }),
  setCompletion: (info) => set({ completion: info }),
  setSettingsOpen: (v) => set({ settingsOpen: v }),
  setProfiles: (profiles) => set({ profiles }),
  setInstallations: (installations) => set({ installations }),

  // -- Snapshot: atomic state replace ----------------------------------------

  applySnapshot: (data) => {
    const version = data['version'] as number
    const state = (data['state'] ?? {}) as Record<string, unknown>

    const phase = (state['phase'] as string) ?? ''
    const idx = ALL_PHASES.indexOf(phase)
    const donePhases = idx === -1 ? [...ALL_PHASES] : ALL_PHASES.slice(0, idx)

    // Transform primary_agent
    const rawPrimary = state['primary_agent'] as Record<string, unknown> | null
    const primaryAgent = rawPrimary ? transformAgent(rawPrimary) : null

    // Transform scouts
    const rawScouts = (state['scouts'] ?? {}) as Record<string, Record<string, unknown>>
    const scouts: Record<string, AgentInfo> = {}
    for (const [id, a] of Object.entries(rawScouts)) {
      scouts[id] = transformAgent(a)
    }

    // Transform completed_agents
    const rawCompleted = (state['completed_agents'] ?? []) as Record<string, unknown>[]
    const completedAgents = rawCompleted.map(transformAgent)

    // Transform artifacts
    const rawArtifacts = (state['artifacts'] ?? {}) as Record<string, Record<string, unknown>>
    const artifacts: Record<string, ArtifactFile> = {}
    for (const [path, a] of Object.entries(rawArtifacts)) {
      artifacts[path] = transformArtifact(a)
    }

    // Transform active_interaction: strip backend's interaction_type discriminator,
    // map to frontend Interaction.type.
    let activeInteraction: Interaction | null = null
    const rawInteraction = state['active_interaction'] as Record<string, unknown> | null
    if (rawInteraction) {
      const itype = interactionTypeToFrontend(rawInteraction['interaction_type'] as string)
      const { interaction_type: _drop, ...interactionPayload } = rawInteraction
      activeInteraction = { type: itype as Interaction['type'], ...interactionPayload } as Interaction
    }

    // Transform notifications
    const rawNotifs = (state['notifications'] ?? []) as Record<string, unknown>[]
    const notifications: NotificationEntry[] = rawNotifs.map((n) => ({
      id: crypto.randomUUID(),
      type: (n['type'] as string) ?? 'unknown',
      severity: SEVERITY_MAP[(n['type'] as string) ?? ''] ?? 'info',
      message: (n['message'] as string) ?? (n['error'] as string) ?? '',
    }))

    // Transform activity_log
    // The backend fold appends tool_called, tool_completed, and thinking as raw
    // entries.  Reconstruct the collapsed one-entry-per-call view that the live
    // applyEvent fold produces: exclude tool_completed (used only to determine
    // inFlight state) and thinking (rendered separately as isThinking indicator).
    const rawLog = (state['activity_log'] ?? []) as Record<string, unknown>[]
    const completedCallIds = new Set(
      rawLog
        .filter(e => e['event_type'] === 'tool_completed')
        .map(e => e['call_id'] as string)
        .filter(Boolean)
    )
    const activityLog: ActivityEntry[] = rawLog
      .filter(e => e['event_type'] !== 'tool_completed' && e['event_type'] !== 'thinking')
      .map((e) => {
        const callId = e['call_id'] as string | undefined
        const isToolCall = e['event_type'] === 'tool_called'
        const inFlight = isToolCall ? !completedCallIds.has(callId ?? '') : false
        return {
          tool:    (e['tool'] as string) ?? (e['event_type'] as string) ?? '',
          summary: (e['summary'] as string) ?? (e['delta'] as string) ?? '',
          inFlight,
          callId,
          ts:      e['ts'] as string | undefined,
        }
      })

    const completion = state['completion'] as CompletionInfo | null

    // Transform config fields
    const configProfiles: Profile[] = ((state['config_profiles'] ?? []) as Record<string, unknown>[]).map(p => ({
      name: p['name'] as string,
      read_only: (p['read_only'] as boolean) ?? false,
      tiers: (p['tiers'] as Record<string, ProfileTierConfig>) ?? {},
    }))

    const configInstallations: Installation[] = ((state['config_installations'] ?? []) as Record<string, unknown>[]).map(i => ({
      alias: i['alias'] as string,
      runner_type: i['runner_type'] as string,
      binary: i['binary'] as string,
      extra_args: (i['extra_args'] as string[]) ?? [],
    }))

    set({
      lastVersion: version,
      phase,
      runStarted: phase !== '',
      donePhases,
      primaryAgent,
      scouts,
      completedAgents,
      artifacts,
      activeInteraction,
      notifications,
      activityLog,
      streamBuffer: (state['stream_buffer'] as string) ?? '',
      isThinking: false,
      completion: completion ?? null,
      // Configuration
      configProfiles,
      configInstallations,
      configActiveProfile: (state['config_active_profile'] as string) ?? 'balanced',
      configScoutConcurrency: (state['config_scout_concurrency'] as number) ?? 8,
      configRunners: (state['config_runners'] ?? []) as RunnerInfo[],
    })
  },

  // -- Event fold: mirrors backend fold --------------------------------------

  applyEvent: (event) => {
    const eventType = event['event_type'] as string
    const version = event['version'] as number
    const agentId = event['agent_id'] as string | null

    set((s) => {
      // Update lastVersion
      const base = { lastVersion: version }

      switch (eventType) {

        // ── Lifecycle ──────────────────────────────────────────────────────

        case 'phase_started': {
          const phase = event['phase'] as string
          const idx = ALL_PHASES.indexOf(phase)
          const donePhases = idx === -1 ? [...ALL_PHASES] : ALL_PHASES.slice(0, idx)
          return { ...base, phase, runStarted: true, donePhases }
        }

        case 'agent_spawned': {
          const isPrimary = event['is_primary'] as boolean ?? true
          const agent: AgentInfo = {
            agentId:        (event['agent_id'] as string) ?? agentId ?? '',
            role:           event['role'] as string,
            model:          event['model'] as string | null,
            step:           0,
            stepName:       '',
            startedAt:      (event['started_at_ms'] as number) ?? 0,
            tokensSent:     0,
            tokensReceived: 0,
          }
          if (isPrimary) {
            return { ...base, primaryAgent: agent }
          } else {
            return { ...base, scouts: { ...s.scouts, [agent.agentId]: agent } }
          }
        }

        case 'agent_spawn_failed': {
          const notif: NotificationEntry = {
            id: crypto.randomUUID(),
            type: 'agent_spawn_failed',
            severity: 'error',
            message: (event['message'] as string) ?? 'Agent spawn failed',
          }
          return { ...base, notifications: [...s.notifications, notif] }
        }

        case 'agent_step_advanced': {
          const step = event['step'] as number
          const stepName = (event['step_name'] as string) ?? ''
          const usage = event['usage'] as Record<string, number> | undefined
          if (s.primaryAgent?.agentId === agentId) {
            return { ...base, primaryAgent: { ...s.primaryAgent, step, stepName,
              tokensSent: s.primaryAgent.tokensSent + (usage?.['input_tokens'] ?? 0),
              tokensReceived: s.primaryAgent.tokensReceived + (usage?.['output_tokens'] ?? 0),
            } }
          } else if (agentId && agentId in s.scouts) {
            const scout = s.scouts[agentId]
            return { ...base, scouts: { ...s.scouts, [agentId]: { ...scout, step, stepName,
              tokensSent: scout.tokensSent + (usage?.['input_tokens'] ?? 0),
              tokensReceived: scout.tokensReceived + (usage?.['output_tokens'] ?? 0),
            } } }
          }
          return base
        }

        case 'agent_exited': {
          const error = event['error'] as string | undefined
          const usage = event['usage'] as Record<string, number> | undefined
          const newNotifs = error ? [
            ...s.notifications,
            {
              id: crypto.randomUUID(),
              type: 'agent_exited_error',
              severity: 'error' as const,
              message: `Agent exited with error: ${error}`,
            },
          ] : s.notifications

          // Mirror backend _accumulate_usage: apply final token delta before
          // moving the agent to completedAgents.
          function applyUsage(agent: AgentInfo): AgentInfo {
            if (!usage) return agent
            return {
              ...agent,
              tokensSent:     agent.tokensSent     + (usage['input_tokens']  ?? 0),
              tokensReceived: agent.tokensReceived  + (usage['output_tokens'] ?? 0),
            }
          }

          if (s.primaryAgent?.agentId === agentId) {
            const finalAgent = applyUsage(s.primaryAgent)
            return { ...base, primaryAgent: null, completedAgents: [...s.completedAgents, finalAgent], notifications: newNotifs }
          } else if (agentId && agentId in s.scouts) {
            const finalAgent = applyUsage(s.scouts[agentId])
            const { [agentId]: _, ...rest } = s.scouts
            return { ...base, scouts: rest, completedAgents: [...s.completedAgents, finalAgent], notifications: newNotifs }
          }
          return { ...base, notifications: newNotifs }
        }

        case 'workflow_completed': {
          const completion: CompletionInfo = {
            success: event['success'] as boolean,
            summary: (event['summary'] as string) ?? '',
            error:   event['error'] as string | undefined,
          }
          return { ...base, completion }
        }

        // ── Activity ───────────────────────────────────────────────────────

        case 'tool_called': {
          const entry: ActivityEntry = {
            tool:     (event['tool'] as string) ?? 'tool',
            summary:  (event['summary'] as string) ?? '',
            inFlight: true,
            callId:   event['call_id'] as string,
            ts:       new Date().toISOString(),
          }
          return { ...base, activityLog: [...s.activityLog, entry], isThinking: false }
        }

        case 'tool_completed': {
          const callId = event['call_id'] as string
          return {
            ...base,
            activityLog: s.activityLog.map(e =>
              e.callId === callId ? { ...e, inFlight: false } : e
            ),
          }
        }

        case 'thinking':
          return { ...base, isThinking: true }

        case 'stream_delta':
          return { ...base, streamBuffer: s.streamBuffer + ((event['delta'] as string) ?? ''), isThinking: false }

        case 'stream_cleared':
          return { ...base, streamBuffer: '', isThinking: false }

        // ── Interactions ───────────────────────────────────────────────────

        case 'questions_asked': {
          const interaction: Interaction = {
            type:      'ask',
            token:     event['token'] as string,
            questions: (event['questions'] as AskQuestion[]) ?? [],
          }
          return { ...base, activeInteraction: interaction }
        }

        case 'questions_answered':
          return { ...base, activeInteraction: null }

        case 'artifact_review_requested': {
          const interaction: Interaction = {
            type:        'artifact-review',
            token:       event['token'] as string,
            path:        event['path'] as string,
            description: event['description'] as string | undefined,
            content:     (event['content'] as string) ?? '',
          }
          return { ...base, activeInteraction: interaction }
        }

        case 'artifact_reviewed':
          return { ...base, activeInteraction: null }

        case 'workflow_decision_requested': {
          const interaction: Interaction = {
            type:        'workflow-decision',
            token:       event['token'] as string,
            chat_turns:  (event['chat_turns'] as ChatTurn[]) ?? [],
          }
          return { ...base, activeInteraction: interaction }
        }

        case 'workflow_decided':
          return { ...base, activeInteraction: null }

        // ── Resources ──────────────────────────────────────────────────────

        case 'artifact_created':
        case 'artifact_modified': {
          const path = event['path'] as string
          const artifact: ArtifactFile = {
            path,
            size:       (event['size'] as number) ?? 0,
            modifiedAt: (event['modified_at'] as number) ?? 0,
          }
          return { ...base, artifacts: { ...s.artifacts, [path]: artifact } }
        }

        case 'artifact_removed': {
          const path = event['path'] as string
          const { [path]: _, ...rest } = s.artifacts
          return { ...base, artifacts: rest }
        }

        // ── Configuration ──────────────────────────────────────────────────

        case 'probe_completed': {
          return { ...base, configRunners: (event['runners'] as RunnerInfo[]) ?? [] }
        }

        case 'installation_created': {
          const inst: Installation = {
            alias:       event['alias'] as string,
            runner_type: event['runner_type'] as string,
            binary:      event['binary'] as string,
            extra_args:  (event['extra_args'] as string[]) ?? [],
          }
          return { ...base, configInstallations: [...s.configInstallations, inst] }
        }

        case 'installation_modified': {
          const alias = event['alias'] as string
          const updated: Installation = {
            alias,
            runner_type: event['runner_type'] as string,
            binary:      event['binary'] as string,
            extra_args:  (event['extra_args'] as string[]) ?? [],
          }
          return {
            ...base,
            configInstallations: s.configInstallations.map(i =>
              i.alias === alias ? updated : i
            ),
          }
        }

        case 'installation_removed': {
          const alias = event['alias'] as string
          return { ...base, configInstallations: s.configInstallations.filter(i => i.alias !== alias) }
        }

        case 'profile_created': {
          const profile: Profile = {
            name:      event['name'] as string,
            read_only: (event['read_only'] as boolean) ?? false,
            tiers:     (event['tiers'] as Record<string, ProfileTierConfig>) ?? {},
          }
          return { ...base, configProfiles: [...s.configProfiles, profile] }
        }

        case 'profile_modified': {
          const name = event['name'] as string
          const updated: Profile = {
            name,
            read_only: (event['read_only'] as boolean) ?? false,
            tiers:     (event['tiers'] as Record<string, ProfileTierConfig>) ?? {},
          }
          const exists = s.configProfiles.some(p => p.name === name)
          return {
            ...base,
            configProfiles: exists
              ? s.configProfiles.map(p => p.name === name ? updated : p)
              : [...s.configProfiles, updated],
          }
        }

        case 'profile_removed': {
          const name = event['name'] as string
          return {
            ...base,
            configProfiles: s.configProfiles.filter(p => p.name !== name),
          }
        }

        case 'active_profile_changed': {
          return { ...base, configActiveProfile: (event['name'] as string) ?? 'balanced' }
        }

        case 'scout_concurrency_changed': {
          return { ...base, configScoutConcurrency: (event['value'] as number) ?? 8 }
        }

        default:
          return base
      }
    })
  },
}))

export type KoanStore = typeof useStore
