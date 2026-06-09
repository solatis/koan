/**
 * NewRunForm -- standalone form page for starting a new koan run.
 * Reads profiles and workflows from the store. Workflows are sourced from
 * settings.workflows (populated at server startup via the workflows_listed
 * projection event) rather than hard-coded.
 * M4: installation selection removed; provider credentials gate run start.
 * Used in: landing page when no run is active.
 */

import { useState, useEffect, useMemo } from 'react'
import { useStore } from '../../store/index'
import { useFileAttachment } from '../../hooks/useFileAttachment'
import * as api from '../../api/client'
import { SectionLabel } from '../atoms/SectionLabel'
import { Button } from '../atoms/Button'
// StatusDot removed in M4: installation status indicators deleted with the installation section.
import { FileChip } from '../atoms/FileChip'
import './NewRunForm.css'

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

export function NewRunForm() {
  const [task, setTask] = useState('')
  const [profile, setProfile] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [workflow, setWorkflow] = useState<string>('plan')
  const [projectDir, setProjectDir] = useState('')
  const attach = useFileAttachment()

  const profilesDict = useStore(s => s.settings.profiles)
  // installationsDict removed in M4: installation concept deleted.
  const defaultProfile = useStore(s => s.settings.defaultProfile)
  const workflows = useStore(s => s.settings.workflows)
  const lastCompletion = useStore(s => s.lastCompletion)
  const setLastCompletion = useStore(s => s.setLastCompletion)

  const profiles = useMemo(() => Object.values(profilesDict), [profilesDict])

  useEffect(() => {
    api.getInitialPrompt().then(data => {
      if (data.prompt) setTask(data.prompt)
      if (data.project_dir) setProjectDir(data.project_dir)
    })
  }, [])

  useEffect(() => {
    if (profiles.length > 0 && !profile) {
      const def = profiles.find(p => p.name === defaultProfile) ?? profiles[0]
      setProfile(def.name)
    }
  }, [profiles, profile, defaultProfile])

  // When the workflows list arrives from the projection, ensure the selected
  // workflow is still valid. Default to 'plan' if present, otherwise the first
  // entry. Leave the selection unchanged while the list is empty (not yet arrived).
  useEffect(() => {
    if (workflows.length === 0) return
    const ids = workflows.map(w => w.id)
    if (!ids.includes(workflow)) {
      setWorkflow(ids.includes('plan') ? 'plan' : ids[0])
    }
  }, [workflows])

  // M4: preflight/selectedInstallations removed -- installation concept deleted.
  // The backend gates run start on provider credential availability.

  const handleStart = async () => {
    const trimmed = task.trim()
    if (!trimmed) { setError('Please enter a task description'); return }
    if (!profile) { setError('Please select a profile'); return }
    setError(null); setLoading(true)
    try {
      const attachmentIds = attach.fileIds.length > 0 ? attach.fileIds : undefined
      const result = await api.startRun(trimmed, profile, undefined, workflow, attachmentIds)
      if (!result.ok) {
        setError(result.message ?? 'Failed to start run')
      } else {
        // Clear chips so they don't re-display on the next run attempt.
        attach.clearFiles()
      }
    } catch { setError('Network error') }
    finally { setLoading(false) }
  }

  return (
    <div className="nrf">
      {/* Last-completion banner: shown after navigating away from a completed run.
          success=true -> teal accent; success=false -> red accent. Dismissed by user. */}
      {lastCompletion && (
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
            onClick={() => setLastCompletion(null)}
          >
            {'x'}
          </button>
        </div>
      )}
      <div className="nrf-header">
        <h1 className="nrf-title">New Run</h1>
        <div className="nrf-project">{projectDir || '—'}</div>
      </div>

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
                onClick={() => setWorkflow(w.id)}
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
          <textarea className="nrf-textarea" value={task} onChange={e => setTask(e.target.value)} rows={4}
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

      {/* Configuration */}
      <div className="nrf-card">
        <SectionLabel>Configuration</SectionLabel>
        <div className="nrf-config-fields">
          <div className="nrf-field">
            <div className="nrf-field-label">Profile</div>
            <select className="nrf-real-select" value={profile} onChange={e => setProfile(e.target.value)}>
              {profiles.map(p => (
                <option key={p.name} value={p.name}>{p.name}{p.readOnly ? ' (built-in)' : ''}</option>
              ))}
            </select>
          </div>

          {/* Agent Installations section removed in M4: installation concept deleted. */}

        </div>
      </div>

      {error && <div className="nrf-error">{error}</div>}

      {/* M4: !hasRunners and !installationsReady guards removed; provider credentials
          gate run start at the backend (api_start_run checks provider_status). */}
      <Button variant="primary" onClick={handleStart}
        disabled={loading || workflows.length === 0}>
        {loading ? 'Starting...' : 'Start Run'}
      </Button>
    </div>
  )
}

export default NewRunForm
