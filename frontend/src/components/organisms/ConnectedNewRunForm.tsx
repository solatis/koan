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
 * Moved from App.tsx to this module in M5.  Shared helpers (toThinkingOptions,
 * buildConnectionViews, LISTING_CAPABLE_TYPES) imported from modelConfig.ts.
 */

import { useState, useEffect, useMemo, useRef } from 'react'
import { useNavigate } from 'react-router'
import { useStore } from '../../store/index'
import { useFileAttachment } from '../../hooks/useFileAttachment'
import * as api from '../../api/client'
import { buildConnectionViews, toThinkingOptions, LISTING_CAPABLE_TYPES } from './modelConfig'
import { NewRunForm, type OverrideAssignment, type WorkflowRole, type ConfigReadiness } from './NewRunForm'

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
  const [modelsLoading, setModelsLoading] = useState<Record<string, boolean>>({})

  // Seed projectDir from the backend once on mount.
  useEffect(() => {
    api.getInitialPrompt().then(r => { if (r.project_dir) setProjectDir(r.project_dir) })
  }, [])

  const { connections, modelsByConnection } = buildConnectionViews(settings, modelsLoading)

  // Default per-run overrides from the current $last slot assignments.
  const defaultOverrides = useMemo((): Record<WorkflowRole, OverrideAssignment> => {
    const cmById: Record<string, typeof settings.configuredModels[0]> = {}
    for (const cm of settings.configuredModels) cmById[cm.id] = cm
    const capById: Record<string, typeof settings.modelCapabilities[0]> = {}
    for (const cap of settings.modelCapabilities) capById[cap.configuredModelId] = cap
    const lastPreset = settings.presets['$last']

    function makeOverride(slot: 'strong' | 'standard' | 'cheap'): OverrideAssignment {
      const sa = lastPreset?.slots[slot]
      if (!sa) return { connectionId: null, modelId: null, thinking: null, thinkingOptions: [] }
      const cm = cmById[sa.configuredModelId]
      if (!cm) return { connectionId: null, modelId: null, thinking: null, thinkingOptions: [] }
      const cap = capById[sa.configuredModelId]
      const rawModes = cap?.thinkingModes ?? []
      const thinkingOptions = toThinkingOptions(rawModes)
      return { connectionId: cm.connectionId, modelId: cm.modelId, thinking: sa.thinking, thinkingOptions }
    }
    return { strong: makeOverride('strong'), standard: makeOverride('standard'), cheap: makeOverride('cheap') }
  }, [settings])

  const [overrides, setOverrides] = useState<Record<WorkflowRole, OverrideAssignment>>(defaultOverrides)

  // Re-sync override defaults when the persisted slot assignments change (e.g.
  // after a settings save). Key on a VALUE signature, NOT defaultOverrides'
  // object identity: the SSE store replaces `settings` (and recomputes
  // defaultOverrides) on EVERY patch, so an identity-keyed effect would fire on
  // the provider_models_listed patch that listConnectionModels triggers and
  // clobber an in-progress connection-only override. Re-seed PER ROLE so a
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
        // Only trigger model listing for listing-capable connection types;
        // non-listing connections (voyage, bedrock) use the free-text picker.
        const connType = settings.connections.find(c => c.id === value)?.connectionType
        if (connType && LISTING_CAPABLE_TYPES.has(connType)) {
          setModelsLoading(p => ({ ...p, [value]: true }))
          api.listConnectionModels(value).then(res => {
            setModelsLoading(p => ({ ...p, [value]: false }))
            if (!res.ok) pushToast(res.message ?? 'Failed to load models', 'error')
          })
        }
        return { ...prev, [role]: { connectionId: value, modelId: null, thinking: null, thinkingOptions: current.thinkingOptions } }
      }
      if (field === 'model') {
        const cap = settings.modelCapabilities.find(c => {
          const cm = settings.configuredModels.find(m => m.modelId === value && m.connectionId === current.connectionId)
          return cm && c.configuredModelId === cm.id
        })
        const rawModes = cap?.thinkingModes ?? []
        const thinkingOptions = toThinkingOptions(rawModes)
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
