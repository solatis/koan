/**
 * NewRunForm — standalone form page for starting a new koan run.
 * Reads profiles and installations from the store, manages form state
 * internally, and calls the API to start a run.
 * Used in: landing page when no run is active.
 */

import { useState, useEffect, useMemo } from 'react'
import { useStore } from '../../store/index'
import { useFileAttachment } from '../../hooks/useFileAttachment'
import * as api from '../../api/client'
import { SectionLabel } from '../atoms/SectionLabel'
import { Button } from '../atoms/Button'
import { StatusDot } from '../atoms/StatusDot'
import { FileChip } from '../atoms/FileChip'
import './NewRunForm.css'

const PaperclipIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.49" />
  </svg>
)

export function NewRunForm() {
  const [task, setTask] = useState('')
  const [profile, setProfile] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedInstallations, setSelectedInstallations] = useState<Record<string, string>>({})
  const [workflow, setWorkflow] = useState<'plan' | 'milestones' | 'curation'>('plan')
  const [projectDir, setProjectDir] = useState('')
  const attach = useFileAttachment()

  const profilesDict = useStore(s => s.settings.profiles)
  const installationsDict = useStore(s => s.settings.installations)
  const defaultProfile = useStore(s => s.settings.defaultProfile)
  const lastCompletion = useStore(s => s.lastCompletion)
  const setLastCompletion = useStore(s => s.setLastCompletion)

  const profiles = useMemo(() => Object.values(profilesDict), [profilesDict])
  const installations = useMemo(() => Object.values(installationsDict), [installationsDict])
  const hasRunners = installations.some(i => i.available)

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

  const preflight = useMemo(() => {
    const sel = profiles.find(p => p.name === profile)
    if (!sel) return null
    const requiredTypes = new Set<string>()
    for (const tierVal of Object.values(sel.tiers)) {
      if (typeof tierVal === 'string') {
        const inst = installationsDict[tierVal]
        if (inst) requiredTypes.add(inst.runnerType)
        else requiredTypes.add(tierVal)
      }
    }
    const byType: Record<string, { alias: string; binary: string }[]> = {}
    for (const rt of requiredTypes) {
      byType[rt] = installations.filter(i => i.runnerType === rt && i.available).map(i => ({ alias: i.alias, binary: i.binary }))
    }
    return { types: [...requiredTypes].sort(), byType }
  }, [profile, profiles, installations, installationsDict])

  useEffect(() => {
    if (!preflight) { setSelectedInstallations({}); return }
    const sel: Record<string, string> = {}
    for (const rt of preflight.types) {
      const insts = preflight.byType[rt] || []
      const def = insts.find(i => i.alias === `${rt}-default`) ?? insts[0]
      if (def) sel[rt] = def.alias
    }
    setSelectedInstallations(sel)
  }, [preflight])

  const installationsReady = preflight ? preflight.types.every(rt => selectedInstallations[rt]) : false

  const handleStart = async () => {
    const trimmed = task.trim()
    if (!trimmed) { setError('Please enter a task description'); return }
    if (!profile) { setError('Please select a profile'); return }
    if (!installationsReady) { setError('Please select an installation for each required runner type'); return }
    setError(null); setLoading(true)
    try {
      const result = await api.startRun(trimmed, profile, selectedInstallations, workflow)
      if (!result.ok) setError(result.message ?? 'Failed to start run')
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
        <div className="nrf-wf-grid">
          <button className={`nrf-wf-option${workflow === 'plan' ? ' nrf-wf-option--selected' : ''}`}
            onClick={() => setWorkflow('plan')}>
            <span className={`nrf-wf-radio${workflow === 'plan' ? ' nrf-wf-radio--selected' : ''}`}>
              {workflow === 'plan' && <span className="nrf-wf-radio-inner" />}
            </span>
            <span className="nrf-wf-info">
              <span className="nrf-wf-name">Plan</span>
              <span className="nrf-wf-desc">Plan an approach, review it, then execute</span>
            </span>
          </button>
          <button className={`nrf-wf-option${workflow === 'milestones' ? ' nrf-wf-option--selected' : ''}`}
            onClick={() => setWorkflow('milestones')}>
            <span className={`nrf-wf-radio${workflow === 'milestones' ? ' nrf-wf-radio--selected' : ''}`}>
              {workflow === 'milestones' && <span className="nrf-wf-radio-inner" />}
            </span>
            <span className="nrf-wf-info">
              <span className="nrf-wf-name">Milestones</span>
              <span className="nrf-wf-desc">Break work into milestones with phased delivery</span>
            </span>
          </button>
          <button className={`nrf-wf-option${workflow === 'curation' ? ' nrf-wf-option--selected' : ''}`}
            onClick={() => setWorkflow('curation')}>
            <span className={`nrf-wf-radio${workflow === 'curation' ? ' nrf-wf-radio--selected' : ''}`}>
              {workflow === 'curation' && <span className="nrf-wf-radio-inner" />}
            </span>
            <span className="nrf-wf-info">
              <span className="nrf-wf-name">Memory</span>
              <span className="nrf-wf-desc">Review, bootstrap, or maintain project knowledge</span>
            </span>
          </button>
        </div>
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

          {preflight && preflight.types.length > 0 && (
            <div className="nrf-field">
              <div className="nrf-field-label">Agent Installations</div>
              <div className="nrf-agent-rows">
              {preflight.types.map(rt => {
                const insts = preflight.byType[rt] || []
                const selected = selectedInstallations[rt] || ''
                return (
                  <div key={rt} className="nrf-agent-row">
                    <span className="nrf-agent-chip">
                      <span className="nrf-agent-name">{rt}</span>
                      <StatusDot status={insts.length > 0 && selected ? 'done' : 'failed'} size="sm" />
                    </span>
                    <select className="nrf-real-select nrf-real-select--flex nrf-real-select--sm"
                      value={selected} onChange={e => setSelectedInstallations(prev => ({ ...prev, [rt]: e.target.value }))}>
                      <option value="">-- select --</option>
                      {insts.map(inst => (
                        <option key={inst.alias} value={inst.alias}>{inst.alias} ({inst.binary})</option>
                      ))}
                    </select>
                    {insts.length === 0 && <span className="nrf-missing">Not detected — configure in Settings</span>}
                  </div>
                )
              })}
              </div>
            </div>
          )}

        </div>
      </div>

      {error && <div className="nrf-error">{error}</div>}

      <Button variant="primary" onClick={handleStart}
        disabled={!hasRunners || loading || !installationsReady}>
        {loading ? 'Starting...' : 'Start Run'}
      </Button>

      {!hasRunners && <div className="nrf-error">No available agent installations. Open Settings to add and configure one.</div>}
    </div>
  )
}

export default NewRunForm
