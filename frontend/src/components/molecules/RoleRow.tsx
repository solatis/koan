/**
 * RoleRow -- configuration row for one model role (Settings -> Model roles) or
 * one memory binding (Settings -> Memory).
 *
 * A role is connection + model + thinking + optional context-window override.
 * Layout follows dependency order; the cascade disables each control until its
 * dependency is set. Presentational: auto-save, validation, and error toasts
 * live in the parent. Logic for context_window changes stays in App.tsx
 * (onRoleChange('context_window', value)).
 */

import './RoleRow.css'
import { useState, useEffect } from 'react'
import { RoleMarker } from '../atoms/RoleMarker'
import { Select } from '../atoms/Select'
import { Badge } from '../atoms/Badge'
import { ModelPicker } from './ModelPicker'

export type RoleSlot =
  | 'strong'
  | 'standard'
  | 'cheap'
  | 'embedding'
  | 'memory-llm'
  | 'reflect-llm'

export type RoleRowState = 'assigned' | 'unassigned' | 'broken' | 'no-thinking'

type MarkerRole = 'strong' | 'standard' | 'cheap' | 'memory'

const ROLE_META: Record<RoleSlot, { marker: MarkerRole; name: string; desc: string }> = {
  strong: { marker: 'strong', name: 'Strong', desc: 'Planning & reviews' },
  standard: { marker: 'standard', name: 'Standard', desc: 'Writing code' },
  cheap: { marker: 'cheap', name: 'Cheap', desc: 'Exploration sub-agents' },
  embedding: { marker: 'memory', name: 'Embedding', desc: 'Indexes memory & docs' },
  'memory-llm': { marker: 'memory', name: 'Memory LLM', desc: 'Write-time classification' },
  'reflect-llm': { marker: 'memory', name: 'Reflect LLM', desc: 'koan_reflect loop' },
}

const CONN_PLACEHOLDER = '— select connection —'

export interface RoleRowProps {
  role: RoleSlot
  state: RoleRowState
  /** 'compact': tighter row for the New Run per-run override -- smaller marker,
   *  name-only meta, narrower columns, compact mono controls. Context-window
   *  input is not rendered in compact variant. */
  variant?: 'default' | 'compact'
  connectionId: string | null
  modelId: string | null
  thinking: string | null
  /** Explicit context window override from ConfiguredModel (tokens). null = unset.
   *  Optional -- not rendered in compact variant; defaults to null when omitted. */
  contextWindow?: number | null
  /** Capability-derived context window used as placeholder when contextWindow is null. */
  capabilityContextWindow?: number
  connections: { id: string; listingCapable: boolean }[]
  models: string[]
  families?: { family: string; resolved: string }[]
  modelsLoading?: boolean
  catalogSuggestions?: string[]
  /** When false, ModelPicker suppresses free-text entry (voyage whitelist mode). Default: true. */
  allowFreeText?: boolean
  /** {value, label} pairs: value is the native backend wire token, label is the
   *  display name (e.g. value='disabled', label='off').  Built by the connected
   *  layer via toThinkingOptions so this component stays store-free. */
  thinkingOptions: { value: string; label: string }[]
  onChange: (field: 'connection' | 'model' | 'thinking' | 'context_window', value: string) => void
  showThinking?: boolean
}

export function RoleRow({
  role,
  state,
  variant = 'default',
  connectionId,
  modelId,
  thinking,
  contextWindow = null,
  capabilityContextWindow = 0,
  connections,
  models,
  families,
  modelsLoading,
  catalogSuggestions,
  allowFreeText = true,
  thinkingOptions,
  onChange,
  showThinking = true,
}: RoleRowProps) {
  const meta = ROLE_META[role]
  const broken = state === 'broken'

  // listingCapable for the chosen connection; false when unset or broken (the
  // dead id is not in the connections list).
  const listingCapable = connections.find(c => c.id === connectionId)?.listingCapable ?? false

  const modelDisabled = connectionId == null || broken
  const thinkingEnabled = modelId != null && thinkingOptions.length > 0 && !broken

  // Local display state for the context-window input. Synced from the prop when
  // the prop changes (projection re-sync), but not clobbered mid-edit because we
  // only update display on prop change (the per-slot value-keyed re-sync in App.tsx
  // ensures prop changes only fire when the actual value changes).
  const [cwDisplay, setCwDisplay] = useState(contextWindow != null ? String(contextWindow) : '')
  useEffect(() => {
    setCwDisplay(contextWindow != null ? String(contextWindow) : '')
  }, [contextWindow])

  // Broken: the connection Select shows only the dead id (parent re-supplies
  // real options on repair). Otherwise the live connection list.
  const connOptions =
    broken && connectionId != null
      ? [{ value: connectionId, label: connectionId }]
      : connections.map(c => ({ value: c.id, label: c.id }))

  const rowCls = [
    'mol-role-row',
    variant === 'compact' && 'mol-role-row--compact',
    broken && 'mol-role-row--broken',
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <div className="mol-role-row-wrap">
      <div className={rowCls}>
        <RoleMarker role={meta.marker} size="sm" />

        <div className="mol-role-row__meta">
          <div className="mol-role-row__name">{meta.name}</div>
          {variant !== 'compact' && <div className="mol-role-row__desc">{meta.desc}</div>}
        </div>

        <div className="mol-role-row__conn">
          <Select
            mono
            value={connectionId ?? ''}
            onChange={v => onChange('connection', v)}
            options={connOptions}
            placeholder={CONN_PLACEHOLDER}
          />
          {broken && <Badge variant="error">removed</Badge>}
        </div>

        <div className="mol-role-row__model">
          <ModelPicker
            connectionId={connectionId}
            value={modelId}
            onChange={id => onChange('model', id)}
            models={models}
            families={families}
            loading={modelsLoading}
            listingCapable={listingCapable}
            catalogSuggestions={catalogSuggestions}
            allowFreeText={allowFreeText}
            disabled={modelDisabled}
          />
        </div>

        {showThinking && (
          <div className="mol-role-row__thinking">
            {thinkingEnabled ? (
              <Select
                value={thinking ?? ''}
                onChange={v => onChange('thinking', v)}
                options={thinkingOptions}
                placeholder="—"
              />
            ) : (
              // Kept present (disabled "—") so the column stays aligned across rows.
              <Select disabled value="__none" onChange={() => {}} options={[{ value: '__none', label: '—' }]} />
            )}
          </div>
        )}
      </div>

      {broken && (
        <div className="mol-role-row__broken-help">
          <svg className="mol-role-row__warn" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path
              d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinejoin="round"
            />
            <path d="M12 9v4M12 17h.01" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          </svg>
          <span>Connection removed -- choose another to make this role runnable.</span>
        </div>
      )}

      {variant !== 'compact' && role !== 'embedding' && (
        // Secondary context-window override row. Shown in default variant only;
        // compact (NewRunForm) does not expose per-model context windows.
        // Suppressed for the embedding role: context window is catalog-fixed
        // and not user-configurable (voyage-only; always 32000).
        <div className="mol-role-row__ctx-row">
          <span className="mol-role-row__ctx-label">context window</span>
          <input
            className="mol-role-row__ctx-input"
            type="text"
            inputMode="numeric"
            pattern="[0-9]*"
            value={cwDisplay}
            placeholder={capabilityContextWindow ? String(capabilityContextWindow) : ''}
            onChange={e => {
              const v = e.target.value
              // Allow empty or digits only while typing.
              if (v === '' || /^\d+$/.test(v)) setCwDisplay(v)
            }}
            onBlur={() => {
              // Commit on blur: pass the raw display value to the parent.
              // Parent (App.tsx onRoleChange) parses to positive int or null.
              onChange('context_window', cwDisplay)
            }}
            disabled={modelId == null}
          />
        </div>
      )}
    </div>
  )
}

export default RoleRow
