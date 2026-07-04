/**
 * ConnectedSettingsPage -- store + API connector for the presentational SettingsPage.
 *
 * Reads connections, configuredModels, presets, memoryBindings, providerStatus,
 * modelCapabilities, modelRegistry, providerModels, and defaultScoutConcurrency
 * from the store.  Implements auto-save (per control) with revert-on-reject + toast.
 * Connection test = save-then-list (no pre-save test endpoint exists).
 *
 * Holds a local interim assignments state seeded from the store-derived map.
 * A connection chosen before its model is picked has no persisted home (a saved
 * role is a complete connection:model pair), so the selection lives in local state
 * until a model commits it.  The state is re-synced per-slot on a value signature
 * (JSON.stringify of the derived map, not its object identity) so neither
 * unrelated projection patches nor persistence of a sibling role clobbers an
 * in-progress connection-only selection.
 *
 * Moved from App.tsx to this module in M5.  Shared helpers (toThinkingOptions,
 * buildConnectionViews, slotToMemoryKind, LISTING_CAPABLE_TYPES) extracted to
 * modelConfig.ts to avoid duplicating join logic in ConnectedNewRunForm.
 */

import { useState, useEffect, useMemo, useRef } from 'react'
import { useStore } from '../../store/index'
import * as api from '../../api/client'
import { buildConnectionViews, toThinkingOptions, slotToMemoryKind, LISTING_CAPABLE_TYPES } from './modelConfig'
import { SettingsPage, type RoleAssignment, type RoleSlot, type ConnectionDraft, type TestState } from './SettingsPage'

export function ConnectedSettingsPage() {
  const settings = useStore(s => s.settings)
  const pushToast = useStore(s => s.pushToast)

  const [editingConnection, setEditingConnection] = useState<string | 'new' | null>(null)
  const [connectionDraft, setConnectionDraft] = useState<ConnectionDraft | null>(null)
  const [connectionTestState, setConnectionTestState] = useState<TestState>({ kind: 'idle' })
  const [connectionSaving, setConnectionSaving] = useState(false)
  const [modelsLoading, setModelsLoading] = useState<Record<string, boolean>>({})
  // Pending embedding dimension change: user picked a new dim but hasn't confirmed the re-embed yet.
  const [pendingRebuildDim, setPendingRebuildDim] = useState<number | null>(null)
  // True while the save/rebuild API call is in-flight after user confirms.
  const [rebuildInProgress, setRebuildInProgress] = useState(false)

  const { connections, modelsByConnection } = buildConnectionViews(settings, modelsLoading)

  // Build the full assignments map from presets ($last) + memoryBindings.
  // Named derivedAssignments to distinguish it from the local interim state below.
  const derivedAssignments = useMemo((): Record<RoleSlot, RoleAssignment> => {
    const cmById: Record<string, typeof settings.configuredModels[0]> = {}
    for (const cm of settings.configuredModels) cmById[cm.id] = cm
    const connById: Record<string, typeof settings.connections[0]> = {}
    for (const c of settings.connections) connById[c.id] = c
    const capById: Record<string, typeof settings.modelCapabilities[0]> = {}
    for (const cap of settings.modelCapabilities) capById[cap.configuredModelId] = cap

    const lastPreset = settings.presets['$last']

    // Default embedding-specific fields for all non-embedding slots (and for
    // embedding slots where the catalog lookup is not applicable).
    const EMBEDDING_DEFAULTS = { embeddingDim: null, embeddingDimOptions: [] }

    function resolveSlot(cmId: string | undefined, thinking: string | null): RoleAssignment {
      if (!cmId) return { connectionId: null, modelId: null, thinking: null, state: 'unassigned', thinkingOptions: [], ...EMBEDDING_DEFAULTS }
      const cm = cmById[cmId]
      if (!cm) return { connectionId: null, modelId: null, thinking: null, state: 'broken', thinkingOptions: [], ...EMBEDDING_DEFAULTS }
      const conn = connById[cm.connectionId]
      const cap = capById[cmId]
      if (!conn) return { connectionId: cm.connectionId, modelId: cm.modelId, thinking, state: 'broken', thinkingOptions: [], ...EMBEDDING_DEFAULTS }
      const rawModes = cap?.thinkingModes ?? []
      const thinkingOptions = toThinkingOptions(rawModes)
      return {
        connectionId: cm.connectionId,
        modelId: cm.modelId,
        thinking,
        state: 'assigned',
        thinkingOptions,
        ...EMBEDDING_DEFAULTS,
      }
    }

    const tierSlots: Partial<Record<RoleSlot, RoleAssignment>> = {}
    for (const slot of ['strong', 'standard', 'cheap'] as RoleSlot[]) {
      const sa = lastPreset?.slots[slot]
      tierSlots[slot] = resolveSlot(sa?.configuredModelId, sa?.thinking ?? null)
    }

    const mem = settings.memoryBindings
    const embeddingCmId = mem?.embedding?.configured_model_id
    const embeddingSlotBase = resolveSlot(embeddingCmId, mem?.embedding?.thinking ?? null)

    // Augment the embedding slot with Voyage catalog data for the dimension selector.
    // embeddingModels is the static catalog (pushed once at startup).
    const embeddingModels = settings.embeddingModels ?? []
    let embeddingSlot = embeddingSlotBase
    if (embeddingSlotBase.modelId != null) {
      const catalogEntry = embeddingModels.find(e => e.modelId === embeddingSlotBase.modelId)
      if (catalogEntry != null) {
        // Source embeddingDim from the projection ConfiguredModel (the persisted override).
        const embeddingCm = embeddingCmId != null ? cmById[embeddingCmId] : undefined
        embeddingSlot = {
          ...embeddingSlotBase,
          embeddingDim: embeddingCm?.embeddingDim ?? null,
          embeddingDimOptions: catalogEntry.dimensions,
        }
      }
    }


    return {
      strong: tierSlots.strong!,
      standard: tierSlots.standard!,
      cheap: tierSlots.cheap!,
      embedding: embeddingSlot,
    }
  }, [settings])

  // Local interim assignments. A connection chosen before its model is picked
  // has no persisted home (a saved role is a complete connection:model pair),
  // so the selection lives here until a model commits it. Seeded from the
  // store-derived map and re-synced -- per slot -- when persistence changes it.
  const [assignments, setAssignments] =
    useState<Record<RoleSlot, RoleAssignment>>(derivedAssignments)

  // Value signature of the derived map. Re-sync keys on this, NOT on
  // derivedAssignments' object identity: the SSE store replaces `settings`
  // (and thus recomputes derivedAssignments) on EVERY patch, so an
  // identity-keyed effect would fire on the provider_models_listed patch that
  // listConnectionModels triggers and clobber an in-progress connection-only
  // selection. The stringified values change only when an assignment actually
  // changes (nothing here derives from providerModels).
  const derivedSignature = useMemo(
    () => JSON.stringify(derivedAssignments),
    [derivedAssignments],
  )

  // Previous derived snapshot. Re-seed PER SLOT so persisting one role does
  // not wipe an in-progress (connection-chosen, model-not-yet-picked) edit on
  // another role. Only slots whose derived value changed are refreshed.
  const prevDerivedRef = useRef(derivedAssignments)

  useEffect(() => {
    const prev = prevDerivedRef.current
    setAssignments(local => {
      let next = local
      for (const slot of Object.keys(derivedAssignments) as RoleSlot[]) {
        if (JSON.stringify(derivedAssignments[slot]) !== JSON.stringify(prev[slot])) {
          if (next === local) next = { ...local }
          next[slot] = derivedAssignments[slot]
        }
      }
      return next
    })
    prevDerivedRef.current = derivedAssignments
    // eslint-disable-next-line react-hooks/exhaustive-deps -- re-sync on value
    // change only; derivedAssignments changes ref every patch.
  }, [derivedSignature])

  const onAddConnection = () => {
    setEditingConnection('new')
    setConnectionDraft({ name: '', type: 'anthropic', apiKey: '', endpoint: '', region: '' })
    setConnectionTestState({ kind: 'idle' })
  }

  const onEditConnection = (id: string) => {
    const conn = settings.connections.find(c => c.id === id)
    if (!conn) return
    setEditingConnection(id)
    // Seed draft from existing connection; name is fixed in edit mode.
    setConnectionDraft({
      name: conn.id,
      type: conn.connectionType,
      apiKey: '',
      endpoint: conn.baseUrl ?? '',
      region: conn.region ?? '',
    })
    setConnectionTestState({ kind: 'idle' })
  }

  const onConnectionDraftChange = (draft: ConnectionDraft) => {
    // In edit mode, keep name fixed to the existing connection id so edits to
    // other fields do not create a second connection and orphan the original.
    if (editingConnection && editingConnection !== 'new') {
      setConnectionDraft({ ...draft, name: editingConnection })
    } else {
      setConnectionDraft(draft)
    }
  }

  const onConnectionSave = async () => {
    if (!connectionDraft) return
    setConnectionSaving(true)
    const res = await api.setConnection({
      id: connectionDraft.name,
      type: connectionDraft.type,
      ...(connectionDraft.endpoint ? { base_url: connectionDraft.endpoint } : {}),
      ...(connectionDraft.region ? { region: connectionDraft.region } : {}),
      ...(connectionDraft.apiKey ? { secret: connectionDraft.apiKey } : {}),
    })
    setConnectionSaving(false)
    if (res.ok) {
      setEditingConnection(null)
      setConnectionDraft(null)
    } else {
      pushToast(res.message ?? 'Failed to save connection', 'error')
    }
  }

  const onConnectionCancel = () => {
    setEditingConnection(null)
    setConnectionDraft(null)
    setConnectionTestState({ kind: 'idle' })
  }

  const onConnectionDelete = async () => {
    if (!editingConnection || editingConnection === 'new') return
    const res = await api.deleteConnection(editingConnection)
    if (res.ok) {
      setEditingConnection(null)
      setConnectionDraft(null)
    } else {
      pushToast(res.message ?? 'Failed to delete connection', 'error')
    }
  }

  const onConnectionTest = async () => {
    if (!connectionDraft) return
    setConnectionTestState({ kind: 'pending' })
    // Save first, then list (no pre-save test endpoint exists).
    const saveRes = await api.setConnection({
      id: connectionDraft.name,
      type: connectionDraft.type,
      ...(connectionDraft.endpoint ? { base_url: connectionDraft.endpoint } : {}),
      ...(connectionDraft.region ? { region: connectionDraft.region } : {}),
      ...(connectionDraft.apiKey ? { secret: connectionDraft.apiKey } : {}),
    })
    if (!saveRes.ok) {
      setConnectionTestState({ kind: 'error', message: saveRes.message ?? 'Save failed' })
      return
    }
    const listRes = await api.listConnectionModels(connectionDraft.name)
    if (listRes.ok) {
      setConnectionTestState({ kind: 'ok', models: listRes.count ?? 0 })
    } else {
      setConnectionTestState({ kind: 'error', message: listRes.message ?? 'Listing failed' })
    }
  }

  /**
   * Handles all role-row controls for a given slot.
   *
   * - connection: Records the chosen connection in local interim state (resetting
   *   modelId and thinking -- a new connection invalidates the prior model) then
   *   triggers a model-list fetch for listing-capable connection types. Nothing is
   *   persisted here -- a connection alone is not a saveable role.
   * - model: Persists the complete connection:model pair via setConfiguredModel +
   *   setSlot/setMemoryBinding, then optimistically reflects the new modelId in
   *   local state so the selection shows immediately without waiting for the
   *   projection patch.
   * - thinking: Persists the thinking level via setSlot/setMemoryBinding (using
   *   the already-persisted cmId from the projection store), then optimistically
   *   reflects it in local state.
   * All branches update the local interim assignments state. The per-slot
   * re-sync effect reconciles local state with the projection once a patch lands.
   */
  const onRoleChange = async (slot: RoleSlot, field: 'connection' | 'model' | 'thinking', value: string) => {
    const current = assignments[slot]
    const isTierSlot = slot === 'strong' || slot === 'standard' || slot === 'cheap'

    if (field === 'connection') {
      // Record the chosen connection locally and reset model/thinking before
      // fetching models. A connection alone cannot be persisted (a saved role is
      // a complete connection:model pair), so this stays in local state only.
      setAssignments(prev => ({
        ...prev,
        [slot]: {
          connectionId: value,
          modelId: null,
          thinking: null,
          state: 'unassigned',
          thinkingOptions: [],
          embeddingDim: null,
          embeddingDimOptions: [],
        },
      }))
      // Only call listConnectionModels for listing-capable connection types.
      // Non-listing connections (voyage, bedrock) skip this call and render
      // the ModelPicker free-text branch with no error toast.
      const connType = settings.connections.find(c => c.id === value)?.connectionType
      if (connType && LISTING_CAPABLE_TYPES.has(connType)) {
        setModelsLoading(prev => ({ ...prev, [value]: true }))
        const res = await api.listConnectionModels(value)
        setModelsLoading(prev => ({ ...prev, [value]: false }))
        if (!res.ok) pushToast(res.message ?? 'Failed to load models', 'error')
      }
      return
    }

    if (field === 'model') {
      const connId = current.connectionId
      if (!connId) return
      const cmId = `${connId}:${value}`
      // When the selected value matches a family's resolved id it is a
      // newest-in-family pin; record its provenance so the ConfiguredModel
      // carries resolved_from for audit and display purposes.  Benign if the
      // user separately selects the same id from the flat list -- truthfully,
      // it is the newest at this point in time.
      const pin = (settings.providerFamilies ?? []).find(
        f => f.connectionId === connId && f.resolved === value,
      )
      const cmRes = await api.setConfiguredModel({
        id: cmId,
        connection_id: connId,
        model_id: value,
        ...(pin ? { resolved_from: pin.resolvedFrom } : {}),
        // Full-upsert clobber-safety: always carry embedding_dim so a concurrent
        // dim save is not lost.  For a model change, reset dim to null (use catalog
        // default for the new model).
        ...(slot === 'embedding' ? { embedding_dim: null } : {}),
      })
      if (!cmRes.ok) {
        pushToast(cmRes.message ?? 'Failed to save model', 'error')
        return
      }
      const body = { configured_model_id: cmId, thinking: current.thinking ?? 'disabled' }
      const slotRes = isTierSlot
        ? await api.setSlot(slot, body)
        : await api.setMemoryBinding(slotToMemoryKind(slot), body)
      if (!slotRes.ok) {
        pushToast(slotRes.message ?? 'Failed to assign model', 'error')
        return
      }
      // Optimistic update: reflect the persisted model immediately so the picker
      // shows the selection without waiting for the projection patch to land.
      // thinkingOptions will be filled by the re-sync effect once capabilities arrive.
      setAssignments(prev => ({
        ...prev,
        [slot]: { ...prev[slot], modelId: value, state: 'assigned' },
      }))
      return
    }

    if (field === 'thinking') {
      // Read cmId from the projection store (not local state) -- thinking
      // requires an already-persisted configured model id.
      const cmId = isTierSlot
        ? settings.presets['$last']?.slots[slot]?.configuredModelId
        : settings.memoryBindings?.[slotToMemoryKind(slot) as 'embedding']?.configured_model_id
      if (!cmId) return
      const body = { configured_model_id: cmId, thinking: value }
      const res = isTierSlot
        ? await api.setSlot(slot, body)
        : await api.setMemoryBinding(slotToMemoryKind(slot), body)
      if (!res.ok) {
        pushToast(res.message ?? 'Failed to save thinking mode', 'error')
        return
      }
      // Optimistic update: reflect the persisted thinking level immediately.
      setAssignments(prev => ({
        ...prev,
        [slot]: { ...prev[slot], thinking: value },
      }))
    }

  }

  const onScoutConcurrencyChange = async (value: number) => {
    const res = await api.saveScoutConcurrency(value)
    if (!res.ok) pushToast(res.message ?? 'Failed to save concurrency', 'error')
  }

  const onMaxRetryAttemptsChange = async (value: number) => {
    const res = await api.saveRetrySettings(value, settings.maxRetryWaitSeconds)
    if (!res.ok) pushToast(res.message ?? 'Failed to save retry attempts', 'error')
  }

  const onMaxRetryWaitSecondsChange = async (value: number) => {
    const res = await api.saveRetrySettings(settings.maxRetryAttempts, value)
    if (!res.ok) pushToast(res.message ?? 'Failed to save retry wait', 'error')
  }

  /**
   * Handles embedding dimension selection from the dimension selector.
   *
   * Gating wrapper: if the embedding binding already has an active identity
   * (model + dimension already persisted, meaning memory has been indexed),
   * changing the dimension requires dropping and re-embedding all entries.
   * We gate the save behind an explicit user confirmation (pendingRebuildDim)
   * to avoid accidental rebuilds.
   *
   * If there is no current embedding identity (embedding not yet configured),
   * we save directly without a confirm.
   *
   * Non-recursive: this handler sets pending state and returns; the actual
   * save fires from onEmbeddingDimConfirm.  onRoleChange never calls this.
   */
  const onEmbeddingDimChange = (dim: number) => {
    const embCmId = settings.memoryBindings?.embedding?.configured_model_id
    const embCm = embCmId != null ? settings.configuredModels.find(m => m.id === embCmId) : undefined
    // If there's already a model+dim identity, require explicit confirmation.
    if (embCm != null) {
      setPendingRebuildDim(dim)
    } else {
      // No existing embedding identity: save directly without confirm.
      void saveEmbeddingDim(dim)
    }
  }

  const saveEmbeddingDim = async (dim: number) => {
    const embCmId = settings.memoryBindings?.embedding?.configured_model_id
    if (!embCmId) return
    const embCm = settings.configuredModels.find(m => m.id === embCmId)
    if (!embCm) return
    setRebuildInProgress(true)
    const res = await api.setConfiguredModel({
      id: embCmId,
      connection_id: embCm.connectionId,
      model_id: embCm.modelId,
      ...(embCm.resolvedFrom ? { resolved_from: embCm.resolvedFrom } : {}),
      embedding_dim: dim,
    })
    setRebuildInProgress(false)
    if (!res.ok) {
      pushToast(res.message ?? 'Failed to save embedding dimension', 'error')
    } else if (res.rebuild_error) {
      pushToast(`Re-embed failed: ${res.rebuild_error}`, 'error')
    }
  }

  const onEmbeddingDimConfirm = async () => {
    if (pendingRebuildDim == null) return
    const dim = pendingRebuildDim
    setPendingRebuildDim(null)
    await saveEmbeddingDim(dim)
  }

  const onEmbeddingDimCancel = () => {
    setPendingRebuildDim(null)
  }

  return (
    <SettingsPage
      connections={connections}
      editingConnection={editingConnection}
      connectionDraft={connectionDraft}
      connectionTestState={connectionTestState}
      connectionSaving={connectionSaving}
      onAddConnection={onAddConnection}
      onEditConnection={onEditConnection}
      onConnectionDraftChange={onConnectionDraftChange}
      onConnectionSave={onConnectionSave}
      onConnectionCancel={onConnectionCancel}
      onConnectionDelete={onConnectionDelete}
      onConnectionTest={onConnectionTest}
      assignments={assignments}
      modelsByConnection={modelsByConnection}
      onRoleChange={onRoleChange}
      embeddingRebuildPending={rebuildInProgress}
      embeddingDimConfirmPending={pendingRebuildDim != null}
      onEmbeddingDimChange={onEmbeddingDimChange}
      onEmbeddingDimConfirm={onEmbeddingDimConfirm}
      onEmbeddingDimCancel={onEmbeddingDimCancel}
      scoutConcurrency={settings.defaultScoutConcurrency}
      onScoutConcurrencyChange={onScoutConcurrencyChange}
      maxRetryAttempts={settings.maxRetryAttempts}
      onMaxRetryAttemptsChange={onMaxRetryAttemptsChange}
      maxRetryWaitSeconds={settings.maxRetryWaitSeconds}
      onMaxRetryWaitSecondsChange={onMaxRetryWaitSecondsChange}
    />
  )
}
