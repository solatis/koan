/**
 * ConnectedNewRunForm -- store + API connector for the presentational NewRunForm.
 *
 * Computes readiness from connection/slot availability.  Per-run override rows
 * default from the $last slot assignments; edits are local only (run-scoped,
 * never persisted to global config).  Overrides are forwarded to startRun.
 *
 * Per-run override defaults are re-synced per role on a VALUE signature so an
 * in-progress connection-only override (connection chosen, model not yet picked)
 * survives unrelated SSE projection patches and genuine default changes on
 * sibling roles.
 *
 * Moved from App.tsx to this module in M5. Shared helpers (toThinkingOptions,
 * buildConnectionViews) imported from modelConfig.ts. M3: thinking modes come
 * from configuredModels[].caps.thinkingLevels (no modelCapabilities join).
 */

import { useState, useEffect, useMemo, useRef } from 'react'
import { useNavigate } from 'react-router'
import { useStore } from '../../store/index'
import { useFileAttachment } from '../../hooks/useFileAttachment'
import * as api from '../../api/client'
import { buildConnectionViews, toThinkingOptions } from './modelConfig'
import { NewRunForm, type OverrideAssignment, type WorkflowRole, type ConfigReadiness } from './NewRunForm'

/**
 * Gated thinking-options builder for the New Run override rows. Returns an
 * empty array (which RoleRow renders as its disabled placeholder) when the
 * model is an always-on ollama-cloud model whose only thinking mode is
 * "medium" — pydantic-ai never propagates a thinking mode to these models,
 * so the selector has nothing to choose. Otherwise delegates to
 * toThinkingOptions.
 */
function gatedThinkingOptions(route: string, rawModes: string[]): { value: string; label: string }[] {
  // Always-on ollama-cloud models expose a single ("medium",) mode that the
  // backend applies unconditionally; the selector would be a no-op, so gate
  // it to the disabled placeholder by returning [].
  if (route === 'ollama-cloud' && rawModes.length === 1 && rawModes[0] === 'medium') return []
  return toThinkingOptions(rawModes)
}

export function ConnectedNewRunForm() {
  const settings = useStore(s => s.settings)
  const lastCompletion = useStore(s => s.lastCompletion)
  const setLastCompletion = useStore(s => s.setLastCompletion)
  const pushToast = useStore(s => s.pushToast)
  const navigate = useNavigate()
  const attach = useFileAttachment()

  const [workflow, setWorkflow] = useState('plan')
  const [task, setTask] = useState('')
  const [projectDir, setProjectDir] = useState('')
  const [error, setError] = useState<string | null>(null)
  // Seed projectDir from the backend once on mount.
  useEffect(() => {
    api.getInitialPrompt().then(r => { if (r.project_dir) setProjectDir(r.project_dir) })
  }, [])

  const { connections, modelsByConnection } = buildConnectionViews(settings)

  // Default per-run overrides from the current $last slot assignments.
  const defaultOverrides = useMemo((): Record<WorkflowRole, OverrideAssignment> => {
    const cmById: Record<string, typeof settings.configuredModels[0]> = {}
    for (const cm of settings.configuredModels) cmById[cm.id] = cm
    const connById: Record<string, typeof settings.connections[0]> = {}
    for (const c of settings.connections) connById[c.id] = c
    const lastPreset = settings.presets['$last']

    // makeOverride: thinking modes come from cm.caps.thinkingLevels (the
    // settings_listed snapshot embeds route-aware caps on each configured
    // model -- no separate modelCapabilities join). Thinking options are
    // gated for always-on ollama-cloud models (single "medium" mode).
    function makeOverride(slot: 'strong' | 'standard' | 'cheap'): OverrideAssignment {
      const sa = lastPreset?.slots[slot]
      if (!sa) return { connectionId: null, modelId: null, thinking: null, thinkingOptions: [] }
      const cm = cmById[sa.configuredModelId]
      if (!cm) return { connectionId: null, modelId: null, thinking: null, thinkingOptions: [] }
      const rawModes = cm.caps?.thinkingLevels ?? []
      // Gate thinking options: always-on ollama-cloud (single "medium" mode)
      // renders the disabled placeholder via empty thinkingOptions. conn may be
      // undefined if the connection was removed; '' falls through to normal.
      const conn = connById[cm.connectionId]
      const thinkingOptions = gatedThinkingOptions(conn?.route ?? '', rawModes)
      return { connectionId: cm.connectionId, modelId: cm.modelId, thinking: sa.thinking, thinkingOptions }
    }
    return { strong: makeOverride('strong'), standard: makeOverride('standard'), cheap: makeOverride('cheap') }
  }, [settings])

  const [overrides, setOverrides] = useState<Record<WorkflowRole, OverrideAssignment>>(defaultOverrides)

  // Re-sync override defaults when the persisted slot assignments change (e.g.
  // after a settings save). Key on a VALUE signature, NOT defaultOverrides'
  // object identity: the SSE store replaces `settings` (and recomputes
  // defaultOverrides) on EVERY patch, so an identity-keyed effect would fire on
  // every settings_listed snapshot and clobber an in-progress connection-only
  // override. Re-seed PER ROLE so a
  // genuine change to one role's default does not wipe an in-progress edit on
  // another role.
  const defaultOverridesSignature = useMemo(
    () => JSON.stringify(defaultOverrides),
    [defaultOverrides],
  )
  const prevDefaultOverridesRef = useRef(defaultOverrides)
  useEffect(() => {
    const prev = prevDefaultOverridesRef.current
    setOverrides(local => {
      let next = local
      for (const role of Object.keys(defaultOverrides) as WorkflowRole[]) {
        if (JSON.stringify(defaultOverrides[role]) !== JSON.stringify(prev[role])) {
          if (next === local) next = { ...local }
          next[role] = defaultOverrides[role]
        }
      }
      return next
    })
    prevDefaultOverridesRef.current = defaultOverrides
    // eslint-disable-next-line react-hooks/exhaustive-deps -- re-sync on value
    // change only; defaultOverrides changes ref every patch.
  }, [defaultOverridesSignature])

  // Readiness: all three tier slots must resolve to a configured model with a valid connection.
  const readiness = useMemo((): ConfigReadiness => {
    if (connections.length === 0) return 'no-providers'
    const cmById: Record<string, typeof settings.configuredModels[0]> = {}
    for (const cm of settings.configuredModels) cmById[cm.id] = cm
    const connById: Record<string, typeof settings.connections[0]> = {}
    for (const c of settings.connections) connById[c.id] = c
    const lastPreset = settings.presets['$last']
    for (const slot of ['strong', 'standard', 'cheap'] as const) {
      const sa = lastPreset?.slots[slot]
      if (!sa) return 'incomplete'
      const cm = cmById[sa.configuredModelId]
      if (!cm) return 'incomplete'
      if (!connById[cm.connectionId]) return 'incomplete'
    }
    return 'ready'
  }, [settings, connections])

  const onOverrideChange = (role: WorkflowRole, field: 'connection' | 'model' | 'thinking', value: string) => {
    setOverrides(prev => {
      const current = prev[role]
      if (field === 'connection') {
        // M3: no auto-list on connection select -- picker content comes from
        // offeringsByConnection via settings_listed.
        return { ...prev, [role]: { connectionId: value, modelId: null, thinking: null, thinkingOptions: current.thinkingOptions } }
      }
      if (field === 'model') {
        const cm = settings.configuredModels.find(
          m => m.modelId === value && m.connectionId === current.connectionId
        )
        const rawModes = cm?.caps?.thinkingLevels ?? []
        // Gate thinking options for always-on ollama-cloud (single "medium")
        // models; conn lookup inline is fine -- this is a per-change handler.
        const conn = settings.connections.find(c => c.id === current.connectionId)
        const thinkingOptions = gatedThinkingOptions(conn?.route ?? '', rawModes)
        return { ...prev, [role]: { ...current, modelId: value, thinkingOptions } }
      }
      // 'thinking'
      return { ...prev, [role]: { ...current, thinking: value } }
    })
  }

  const onStartRun = async () => {
    setError(null)
    // Build the overrides payload: only include roles with both connection and model set.
    const payload: Record<string, { connection_id: string; model_id: string; thinking: string }> = {}
    for (const role of ['strong', 'standard', 'cheap'] as WorkflowRole[]) {
      const ov = overrides[role]
      if (ov.connectionId && ov.modelId) {
        payload[role] = {
          connection_id: ov.connectionId,
          model_id: ov.modelId,
          thinking: ov.thinking ?? 'disabled',
        }
      }
    }
    const readyAttachments = attach.fileIds
    const res = await api.startRun(task, workflow, readyAttachments, Object.keys(payload).length > 0 ? payload : undefined)
    if (!res.ok) {
      const msg = res.message ?? 'Failed to start run'
      setError(msg)
      pushToast(msg, 'error')
    }
    // On success, SSE run_started drives navigation via App; no navigate() needed here.
  }

  const startDisabled = !task.trim() || readiness !== 'ready'

  return (
    <NewRunForm
      projectDir={projectDir}
      workflows={settings.workflows.map(w => ({ id: w.id, description: w.description }))}
      workflow={workflow}
      onWorkflowChange={setWorkflow}
      task={task}
      onTaskChange={setTask}
      attach={attach}
      lastCompletion={lastCompletion}
      onDismissLastCompletion={() => setLastCompletion(null)}
      error={error}
      readiness={readiness}
      overrides={overrides}
      connections={connections}
      modelsByConnection={modelsByConnection}
      onOverrideChange={onOverrideChange}
      onStartRun={onStartRun}
      onOpenSettings={() => navigate('/settings')}
      startDisabled={startDisabled}
    />
  )
}
