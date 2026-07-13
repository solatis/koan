/**
 * RoleRow -- configuration row for one model role (Settings -> Model roles) or
 * one memory binding (Settings -> Memory).
 *
 * A role is connection + model + thinking.
 * Layout follows dependency order; the cascade disables each control until its
 * dependency is set. Presentational: auto-save, validation, and error toasts
 * live in the parent.
 *
 * M3: shows an "unresolved" Badge when the configured model did not resolve to
 * a known catalog identity, and a neutral Badge with the provenance source
 * (e.g. "catalog") when resolved. Picker content comes from offerings.
 *
 * RoleSlot is now 'strong' | 'standard' | 'cheap' | 'embedding';
 * 'memory-llm' and 'reflect-llm' were removed.
 */

import './RoleRow.css'
import { RoleMarker } from '../atoms/RoleMarker'
import { Select } from '../atoms/Select'
import { Badge } from '../atoms/Badge'
import { ModelPicker } from './ModelPicker'

export type RoleSlot =
  | 'strong'
  | 'standard'
  | 'cheap'
  | 'embedding'

export type RoleRowState = 'assigned' | 'unassigned' | 'broken' | 'no-thinking'

type MarkerRole = 'strong' | 'standard' | 'cheap' | 'memory'

const ROLE_META: Record<RoleSlot, { marker: MarkerRole; name: string; desc: string }> = {
  strong: { marker: 'strong', name: 'Strong', desc: 'Planning & reviews' },
  standard: { marker: 'standard', name: 'Standard', desc: 'Writing code' },
  cheap: { marker: 'cheap', name: 'Cheap', desc: 'Exploration sub-agents' },
  embedding: { marker: 'memory', name: 'Embedding', desc: 'Indexes memory & docs' },
}

const CONN_PLACEHOLDER = '— select connection —'

export interface RoleRowProps {
  role: RoleSlot
  state: RoleRowState
  /** 'compact': tighter row for the New Run per-run override -- smaller marker,
   *  name-only meta, narrower columns, compact mono controls. */
  variant?: 'default' | 'compact'
  connectionId: string | null
  modelId: string | null
  thinking: string | null
  connections: { id: string }[]
  models: string[]
  families?: { family: string; resolved: string }[]
  /** Whether the configured model resolved to a known catalog identity (M3). */
  resolved?: boolean
  /** First provenance source for the configured model's caps, or null. */
  provenanceSource?: string | null
  /** When false, ModelPicker suppresses free-text entry (voyage whitelist mode). Default: true. */
  allowFreeText?: boolean
  /** {value, label} pairs: value is the native backend wire token, label is the
   *  display name (e.g. value='disabled', label='off').  Built by the connected
   *  layer via toThinkingOptions so this component stays store-free. */
  thinkingOptions: { value: string; label: string }[]
  onChange: (field: 'connection' | 'model' | 'thinking', value: string) => void
  showThinking?: boolean
}

export function RoleRow({
  role,
  state,
  variant = 'default',
  connectionId,
  modelId,
  thinking,
  connections,
  models,
  families,
  resolved,
  provenanceSource,
  allowFreeText = true,
  thinkingOptions,
  onChange,
  showThinking = true,
}: RoleRowProps) {
  const meta = ROLE_META[role]
  const broken = state === 'broken'

  const modelDisabled = connectionId == null || broken
  const thinkingEnabled = modelId != null && thinkingOptions.length > 0 && !broken

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
            allowFreeText={allowFreeText}
            disabled={modelDisabled}
          />
          {state === 'assigned' && resolved === false && (
            <Badge variant="error">unresolved</Badge>
          )}
          {state === 'assigned' && resolved && provenanceSource && (
            <Badge variant="neutral">{provenanceSource}</Badge>
          )}
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
    </div>
  )
}

export default RoleRow
