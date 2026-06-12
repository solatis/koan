/**
 * NewRunForm — workflow + description + per-run model override.
 *
 * Three render states by config readiness:
 *  'ready'        → Models override section (three RoleCards) + Start enabled
 *  'incomplete'   → Models section HIDDEN, InlineNotice gate, Start disabled
 *  'no-providers' → NoProvidersBlock replaces the form body entirely
 * Run-readiness (computed by the parent): all three workflow slots resolve to
 * a valid configured model AND ≥1 connection. Memory bindings never gate.
 *
 * Presentational: workflows, description text, attachments, and overrides all
 * arrive via props; the parent owns fetching, uploads, and run start.
 */

import './NewRunForm.css'
import type { ChangeEvent, ClipboardEvent, DragEvent, RefObject } from 'react'
import { SectionLabel } from '../atoms/SectionLabel'
import { Button } from '../atoms/Button'
import { FileChip } from '../atoms/FileChip'
import type { WorkflowRole } from '../molecules/RoleCard'
import { RoleRow } from '../molecules/RoleRow'
import { InlineNotice } from '../molecules/InlineNotice'
import { NoProvidersBlock } from './NoProvidersBlock'
import type { ConnectionSummary, ModelsForConnection } from './SettingsPage'
import type { AttachedFile } from '../../hooks/useFileAttachment'

export type { WorkflowRole }

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ConfigReadiness = 'ready' | 'incomplete' | 'no-providers'

export interface OverrideAssignment {
  connectionId: string | null
  modelId: string | null
  thinking: string | null
  /** {value, label} pairs built by the connected layer; value is the wire token. */
  thinkingOptions: { value: string; label: string }[]
}

export interface WorkflowOption {
  id: string
  description: string
}

export interface LastCompletion {
  success: boolean
  summary?: string | null
  error?: string | null
}

/**
 * Structural slice of useFileAttachment's return value. Declared here (rather
 * than importing the hook) so the component stays free of the api client the
 * hook uploads through; the parent passes the real hook result.
 */
export interface FileAttachmentControls {
  files: AttachedFile[]
  dragProps: {
    onDragEnter: (e: DragEvent) => void
    onDragLeave: (e: DragEvent) => void
    onDragOver: (e: DragEvent) => void
    onDrop: (e: DragEvent) => void
  }
  onPaste: (e: ClipboardEvent) => void
  openPicker: () => void
  inputRef: RefObject<HTMLInputElement | null>
  onInputChange: (e: ChangeEvent<HTMLInputElement>) => void
  removeFile: (id: string) => void
}

export interface NewRunFormProps {
  // Page header
  projectDir: string

  // Workflow section
  workflows: WorkflowOption[]
  workflow: string
  onWorkflowChange: (id: string) => void

  // Description section
  task: string
  onTaskChange: (value: string) => void
  attach?: FileAttachmentControls

  // Last-completion banner + error line
  lastCompletion?: LastCompletion | null
  onDismissLastCompletion?: () => void
  error?: string | null

  // Config readiness + per-run model override
  readiness: ConfigReadiness
  overrides: Record<WorkflowRole, OverrideAssignment>
  connections: ConnectionSummary[]
  modelsByConnection: Record<string, ModelsForConnection>
  onOverrideChange: (role: WorkflowRole, field: 'connection' | 'model' | 'thinking' | 'context_window', value: string) => void
  onStartRun: () => void
  onOpenSettings: () => void
  /** Parent may disable for other reasons (e.g. empty description); OR'd with readiness gating. */
  startDisabled?: boolean
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const PaperclipIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.49" />
  </svg>
)

/**
 * Convert a workflow id (e.g. 'plan', 'milestone-spec') into a Title-cased
 * display name. Splits on '-' and capitalises each token; keeps the rest
 * of each token lowercase so ids like 'PLAN' still render as 'Plan'.
 */
function labelFromId(id: string): string {
  return id
    .split('-')
    .map(t => t.charAt(0).toUpperCase() + t.slice(1).toLowerCase())
    .join(' ')
}

const noop = () => {}

const STUB_ATTACH: FileAttachmentControls = {
  files: [],
  dragProps: { onDragEnter: noop, onDragLeave: noop, onDragOver: noop, onDrop: noop },
  onPaste: noop,
  openPicker: noop,
  inputRef: { current: null },
  onInputChange: noop,
  removeFile: noop,
}

const NO_MODELS: ModelsForConnection = { models: [] }

const OVERRIDE_ROLES: WorkflowRole[] = ['strong', 'standard', 'cheap']

// ---------------------------------------------------------------------------
// NewRunForm
// ---------------------------------------------------------------------------

export function NewRunForm({
  projectDir,
  workflows,
  workflow,
  onWorkflowChange,
  task,
  onTaskChange,
  attach = STUB_ATTACH,
  lastCompletion,
  onDismissLastCompletion,
  error,
  readiness,
  overrides,
  connections,
  modelsByConnection,
  onOverrideChange,
  onStartRun,
  onOpenSettings,
  startDisabled = false,
}: NewRunFormProps) {
  const banner = lastCompletion && (
    <div className={`nrf-last-completion nrf-last-completion--${lastCompletion.success ? 'success' : 'error'}`}>
      <span className="nrf-last-completion-msg">
        {lastCompletion.success
          ? (lastCompletion.summary || 'Previous run completed.')
          : `Previous run failed: ${lastCompletion.error || 'unknown error'}`}
      </span>
      <button
        type="button"
        className="nrf-last-completion-dismiss"
        aria-label="Dismiss"
        onClick={() => onDismissLastCompletion?.()}
      >
        {'x'}
      </button>
    </div>
  )

  const header = (
    <div className="nrf-header">
      <h1 className="nrf-title">New Run</h1>
      <div className="nrf-project">{projectDir || '—'}</div>
    </div>
  )

  // 'no-providers': the gate block replaces the form body entirely.
  if (readiness === 'no-providers') {
    return (
      <div className="nrf">
        {banner}
        {header}
        <div className="nrf-gate">
          <NoProvidersBlock onGoToSettings={onOpenSettings} />
        </div>
      </div>
    )
  }

  const roleConnections = connections.map(c => ({ id: c.id, listingCapable: c.listingCapable }))

  // Overrides never render 'broken' — readiness gating handles that upstream.
  const overrideRow = (role: WorkflowRole) => {
    const o = overrides[role]
    const m = (o.connectionId != null && modelsByConnection[o.connectionId]) || NO_MODELS
    return (
      <RoleRow
        key={role}
        role={role}
        variant="compact"
        state={o.connectionId != null && o.modelId != null ? 'assigned' : 'unassigned'}
        connectionId={o.connectionId}
        modelId={o.modelId}
        thinking={o.thinking}
        connections={roleConnections}
        models={m.models}
        families={m.families}
        modelsLoading={m.loading}
        catalogSuggestions={m.catalogSuggestions}
        thinkingOptions={o.thinkingOptions}
        onChange={(field, value) => onOverrideChange(role, field, value)}
      />
    )
  }

  const startBlocked = readiness !== 'ready' || startDisabled || workflows.length === 0

  return (
    <div className="nrf">
      {banner}
      {header}

      {/* Workflow */}
      <div className="nrf-card">
        <SectionLabel>Workflow</SectionLabel>
        {workflows.length === 0 ? (
          <div className="nrf-helper">Loading workflows...</div>
        ) : (
          <div className="nrf-wf-grid">
            {workflows.map(w => (
              <button
                key={w.id}
                className={`nrf-wf-option${workflow === w.id ? ' nrf-wf-option--selected' : ''}`}
                onClick={() => onWorkflowChange(w.id)}
              >
                <span className={`nrf-wf-radio${workflow === w.id ? ' nrf-wf-radio--selected' : ''}`}>
                  {workflow === w.id && <span className="nrf-wf-radio-inner" />}
                </span>
                <span className="nrf-wf-info">
                  <span className="nrf-wf-name">{labelFromId(w.id)}</span>
                  <span className="nrf-wf-desc">{w.description}</span>
                </span>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Description */}
      <div className="nrf-card">
        <SectionLabel>Description</SectionLabel>
        <div className="nrf-helper">What should this run accomplish?</div>
        <div className="nrf-textarea-wrap" {...attach.dragProps}>
          <textarea className="nrf-textarea" value={task} onChange={e => onTaskChange(e.target.value)} rows={4}
            onPaste={attach.onPaste}
            placeholder="Describe what you want to build..." />
          <button className="nrf-attach-btn" onClick={attach.openPicker} title="Attach files" type="button">
            <PaperclipIcon />
          </button>
          <input ref={attach.inputRef} type="file" multiple className="nrf-file-input" onChange={attach.onInputChange} tabIndex={-1} />
        </div>
        {attach.files.length > 0 && (
          <div className="nrf-chips">
            {attach.files.map(f => (
              <FileChip key={f.id} name={f.name} size={f.size} state={f.state} onRemove={() => attach.removeFile(f.id)} />
            ))}
          </div>
        )}
      </div>

      {/* Models — per-run override, only when the config is runnable */}
      {readiness === 'ready' && (
        <div className="nrf-card">
          <div className="nrf-models-head">
            <SectionLabel>Models</SectionLabel>
            <span className="nrf-models-hint">Defaults from Settings · changes apply to this run only</span>
          </div>
          <div className="nrf-models-cols" aria-hidden="true">
            <span className="nrf-models-cols__spacer" />
            <span className="nrf-models-cols__label nrf-models-cols__label--conn">Provider</span>
            <span className="nrf-models-cols__label nrf-models-cols__label--model">Model</span>
            <span className="nrf-models-cols__label nrf-models-cols__label--think">Thinking</span>
          </div>
          <div className="nrf-models-rows">
            {OVERRIDE_ROLES.map(overrideRow)}
          </div>
        </div>
      )}

      {/* Incomplete config: gate notice instead of the Models section */}
      {readiness === 'incomplete' && (
        <div className="nrf-notice-gate">
          <InlineNotice
            message="Assign a model to all three roles before starting a run."
            action={{ label: 'Open Settings →', onClick: onOpenSettings }}
          />
        </div>
      )}

      {error && <div className="nrf-error">{error}</div>}

      <Button variant="primary" onClick={onStartRun} disabled={startBlocked}>
        Start Run
      </Button>
    </div>
  )
}

export default NewRunForm
