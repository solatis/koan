/**
 * SettingsPage — single-column settings view: Connections → Model roles →
 * Memory → Runtime. Connections come first because the two sections below
 * reference them. Presentational; the parent owns fetching, saving, toasts.
 */

import './SettingsPage.css'
import type { ReactNode } from 'react'
import { ConnectionRow } from '../molecules/ConnectionRow'
import { ConnectionForm, type ConnectionDraft, type TestState } from '../molecules/ConnectionForm'
import { RoleRow, type RoleSlot, type RoleRowState } from '../molecules/RoleRow'
import { SettingRow } from '../molecules/SettingRow'
import { InlineNotice } from '../molecules/InlineNotice'
import { NumberInput } from '../atoms/NumberInput'
import { Select } from '../atoms/Select'
import { Button } from '../atoms/Button'
import type { ProviderType } from '../atoms/ProviderBadge'

// Re-exported so the parent can build props without importing the molecules.
export type { ConnectionDraft, TestState, RoleSlot, RoleRowState }

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ConnectionSummary {
  type: ProviderType
  id: string
  meta: string
  status: 'configured' | 'not-set'
  listingCapable: boolean
}

export interface ModelsForConnection {
  models: string[]
  families?: { family: string; resolved: string }[]
  loading?: boolean
  catalogSuggestions?: string[]
}

export interface RoleAssignment {
  connectionId: string | null
  modelId: string | null
  thinking: string | null
  state: RoleRowState
  /** {value, label} pairs built by the connected layer; value is the wire token. */
  thinkingOptions: { value: string; label: string }[]
  /** Selected Voyage output dimension; null = use catalog default. Relevant for embedding only. */
  embeddingDim: number | null
  /** Available dimension options from the Voyage catalog for the selected model. [] = not applicable. */
  embeddingDimOptions: number[]
}

export interface SettingsPageProps {
  connections: ConnectionSummary[]

  // Connection editing (null = no form open; 'new' = add form)
  editingConnection: string | 'new' | null
  connectionDraft: ConnectionDraft | null
  connectionTestState?: TestState
  connectionSaving?: boolean
  onAddConnection: () => void
  onEditConnection: (id: string) => void
  onConnectionDraftChange: (draft: ConnectionDraft) => void
  onConnectionSave: () => void
  onConnectionCancel: () => void
  onConnectionDelete: () => void
  onConnectionTest: () => void

  // Role + memory assignments
  assignments: Record<RoleSlot, RoleAssignment>
  modelsByConnection: Record<string, ModelsForConnection>
  onRoleChange: (slot: RoleSlot, field: 'connection' | 'model' | 'thinking', value: string) => void

  /** Whether a vector-index rebuild is pending/in-progress after an embedding config change. */
  embeddingRebuildPending: boolean
  /**
   * Whether the user has picked a new dimension that will require a full re-embed
   * and is waiting for explicit confirmation before the save is sent.
   */
  embeddingDimConfirmPending: boolean
  /** Called when the user picks a new embedding output dimension. */
  onEmbeddingDimChange: (dim: number) => void
  /** Called when the user confirms a pending dimension change that would re-embed. */
  onEmbeddingDimConfirm: () => void
  /** Called when the user cancels a pending dimension change. */
  onEmbeddingDimCancel: () => void

  // Runtime
  scoutConcurrency: number
  onScoutConcurrencyChange: (value: number) => void
  maxRetryAttempts: number
  onMaxRetryAttemptsChange: (value: number) => void
  maxRetryWaitSeconds: number
  onMaxRetryWaitSecondsChange: (value: number) => void
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Providers that expose a list-models endpoint, so Test connection makes sense. */
const LISTING_CAPABLE: ReadonlySet<ProviderType> = new Set<ProviderType>([
  'anthropic',
  'openai',
  'google',
  'openrouter',
  'ollama-cloud',
])

const NO_MODELS: ModelsForConnection = { models: [] }

interface SectionCardProps {
  title: string
  hint?: string
  description?: string
  children: ReactNode
}

function SectionCard({ title, hint, description, children }: SectionCardProps) {
  return (
    <section className="settings-card">
      <div className="settings-card-head">
        <div className="settings-card-title">{title}</div>
        {hint && <div className="settings-card-hint">{hint}</div>}
      </div>
      {description && <div className="settings-card-desc">{description}</div>}
      {children}
    </section>
  )
}

// ---------------------------------------------------------------------------
// SettingsPage
// ---------------------------------------------------------------------------

export function SettingsPage({
  connections,
  editingConnection,
  connectionDraft,
  connectionTestState,
  connectionSaving,
  onAddConnection,
  onEditConnection,
  onConnectionDraftChange,
  onConnectionSave,
  onConnectionCancel,
  onConnectionDelete,
  onConnectionTest,
  assignments,
  modelsByConnection,
  onRoleChange,
  embeddingRebuildPending,
  embeddingDimConfirmPending,
  onEmbeddingDimChange,
  onEmbeddingDimConfirm,
  onEmbeddingDimCancel,
  scoutConcurrency,
  onScoutConcurrencyChange,
  maxRetryAttempts,
  onMaxRetryAttemptsChange,
  maxRetryWaitSeconds,
  onMaxRetryWaitSecondsChange,
}: SettingsPageProps) {
  const roleConnections = connections.map(c => ({ id: c.id, listingCapable: c.listingCapable }))

  const connectionForm = (mode: 'add' | 'edit') =>
    connectionDraft && (
      <ConnectionForm
        mode={mode}
        draft={connectionDraft}
        onChange={onConnectionDraftChange}
        onSave={onConnectionSave}
        onCancel={onConnectionCancel}
        onDelete={onConnectionDelete}
        onTest={LISTING_CAPABLE.has(connectionDraft.type) ? onConnectionTest : undefined}
        testState={connectionTestState}
        saving={connectionSaving}
      />
    )

  const roleRow = (slot: RoleSlot, showThinking = true) => {
    const a = assignments[slot]
    const m = (a.connectionId != null && modelsByConnection[a.connectionId]) || NO_MODELS
    // Voyage embedding models: fixed whitelist, no free-text entry.
    const allowFreeText = slot !== 'embedding'
    return (
      <RoleRow
        key={slot}
        role={slot}
        state={a.state}
        connectionId={a.connectionId}
        modelId={a.modelId}
        thinking={a.thinking}
        connections={roleConnections}
        models={m.models}
        families={m.families}
        modelsLoading={m.loading}
        catalogSuggestions={m.catalogSuggestions}
        allowFreeText={allowFreeText}
        thinkingOptions={a.thinkingOptions}
        onChange={(field, value) => onRoleChange(slot, field, value)}
        showThinking={showThinking}
      />
    )
  }

  const embeddingA = assignments['embedding']
  const embeddingDimOptions = embeddingA.embeddingDimOptions
  const embeddingDim = embeddingA.embeddingDim
  const embeddingDimSelectOptions = embeddingDimOptions.map(d => ({
    value: String(d),
    label: String(d),
  }))

  return (
    <div className="settings-page">
      <div className="settings-content">
        <h1 className="settings-title">Settings</h1>

        {/* === CONNECTIONS === */}
        <SectionCard title="Connections" hint="Providers koan can reach.">
          <div className="settings-connections">
            {connections.map(c => (
              <div key={c.id}>
                <ConnectionRow
                  type={c.type}
                  id={c.id}
                  meta={c.meta}
                  status={c.status}
                  active={editingConnection === c.id}
                  onEdit={() => onEditConnection(c.id)}
                />
                {editingConnection === c.id && connectionForm('edit')}
              </div>
            ))}
          </div>
          <div className="settings-add-trigger">
            <Button variant="text" size="sm" onClick={onAddConnection}>
              + Add connection
            </Button>
          </div>
          {editingConnection === 'new' && connectionForm('add')}
        </SectionCard>

        {/* === MODEL ROLES === */}
        <SectionCard
          title="Model roles"
          hint="Any model can fill any role."
          description="koan uses three roles across every workflow. Pick a connection, then a model, then a thinking level."
        >
          <div className="settings-roles">
            {roleRow('strong')}
            {roleRow('standard')}
            {roleRow('cheap')}
          </div>
        </SectionCard>

        {/* === MEMORY === */}
        <SectionCard title="Memory" description="Models used by the memory subsystem.">
          <div className="settings-roles">
            {roleRow('embedding', false)}
            {embeddingDimOptions.length > 0 && (
              <div className="mol-role-row-wrap">
                <div className="mol-role-row__ctx-row">
                  <span className="mol-role-row__ctx-label">output dimensions</span>
                  <Select
                    mono
                    value={embeddingDim != null ? String(embeddingDim) : ''}
                    onChange={v => onEmbeddingDimChange(Number(v))}
                    options={embeddingDimSelectOptions}
                    placeholder="— catalog default —"
                    disabled={embeddingA.modelId == null || embeddingDimConfirmPending || embeddingRebuildPending}
                  />
                </div>
                {embeddingDimConfirmPending && !embeddingRebuildPending && (
                  <>
                    <InlineNotice
                      message="Changing output dimensions will drop and re-embed all memory entries. Memory search is unavailable during the rebuild."
                      action={{ label: 'Re-embed', onClick: onEmbeddingDimConfirm }}
                    />
                    <div style={{ marginTop: '4px' }}>
                      <Button variant="text" size="sm" onClick={onEmbeddingDimCancel}>Cancel</Button>
                    </div>
                  </>
                )}
                {embeddingRebuildPending && (
                  <InlineNotice
                    message="Re-embedding in progress -- memory search is temporarily unavailable."
                  />
                )}
              </div>
            )}
            {roleRow('memory-llm')}
            {roleRow('reflect-llm')}
          </div>
        </SectionCard>

        {/* === RUNTIME === */}
        <SectionCard title="Runtime">
          <SettingRow label="Scout concurrency" description="Maximum number of parallel scout agents">
            <NumberInput value={scoutConcurrency} onChange={onScoutConcurrencyChange} min={1} max={32} />
          </SettingRow>
          <SettingRow label="Max retry attempts" description="Maximum number of transient-error retries before escalating">
            <NumberInput value={maxRetryAttempts} onChange={onMaxRetryAttemptsChange} min={1} max={100} />
          </SettingRow>
          <SettingRow label="Max retry wait (seconds)" description="Backoff ceiling in seconds between retry attempts">
            <NumberInput value={maxRetryWaitSeconds} onChange={onMaxRetryWaitSecondsChange} min={1} max={600} />
          </SettingRow>
        </SectionCard>
      </div>
    </div>
  )
}

export default SettingsPage
