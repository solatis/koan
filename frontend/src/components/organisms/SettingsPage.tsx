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
import { NumberInput } from '../atoms/NumberInput'
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

  // Runtime
  scoutConcurrency: number
  onScoutConcurrencyChange: (value: number) => void
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Providers that expose a list-models endpoint, so Test connection makes sense. */
const LISTING_CAPABLE: ReadonlySet<ProviderType> = new Set<ProviderType>([
  'anthropic',
  'openai',
  'google',
  'lmstudio',
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
  scoutConcurrency,
  onScoutConcurrencyChange,
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
        thinkingOptions={a.thinkingOptions}
        onChange={(field, value) => onRoleChange(slot, field, value)}
        showThinking={showThinking}
      />
    )
  }

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
            {roleRow('memory-llm')}
            {roleRow('reflect-llm')}
          </div>
        </SectionCard>

        {/* === RUNTIME === */}
        <SectionCard title="Runtime">
          <SettingRow label="Scout concurrency" description="Maximum number of parallel scout agents">
            <NumberInput value={scoutConcurrency} onChange={onScoutConcurrencyChange} min={1} max={32} />
          </SettingRow>
        </SectionCard>
      </div>
    </div>
  )
}

export default SettingsPage
