import { useState, useEffect, useMemo } from 'react'
import { useStore } from '../store/index'
import * as api from '../api/client'

export function LandingPage() {
  const [task, setTask] = useState('')
  const [profile, setProfile] = useState('')
  const [scoutConcurrency, setScoutConcurrency] = useState(8)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedInstallations, setSelectedInstallations] = useState<Record<string, string>>({})
  const [workflow, setWorkflow] = useState<'plan' | 'milestones'>('plan')
  const [projectDir, setProjectDir] = useState('')

  // Read from store (fed by SSE — always current, no API fetch needed)
  const profilesDict = useStore(s => s.settings.profiles)
  const installationsDict = useStore(s => s.settings.installations)
  const defaultProfile = useStore(s => s.settings.defaultProfile)
  const defaultScoutConcurrency = useStore(s => s.settings.defaultScoutConcurrency)

  const profiles = useMemo(() => Object.values(profilesDict), [profilesDict])
  const installations = useMemo(() => Object.values(installationsDict), [installationsDict])

  // Available means the binary was probed and found
  const hasRunners = installations.some(i => i.available)

  // Load initial prompt (one-shot, not config state)
  useEffect(() => {
    api.getInitialPrompt().then(data => {
      if (data.prompt) setTask(data.prompt)
      if (data.project_dir) setProjectDir(data.project_dir)
    })
  }, [])

  // Auto-select default profile when profiles arrive from store
  useEffect(() => {
    if (profiles.length > 0 && !profile) {
      const def = profiles.find(p => p.name === defaultProfile) ?? profiles[0]
      setProfile(def.name)
    }
  }, [profiles, profile, defaultProfile])

  // Sync scout concurrency from store
  useEffect(() => {
    setScoutConcurrency(defaultScoutConcurrency)
  }, [defaultScoutConcurrency])

  // Derive preflight locally from store state — no API call needed
  const preflight = useMemo(() => {
    const selectedProfile = profiles.find(p => p.name === profile)
    if (!selectedProfile) return null

    // Profile tiers map role → value. The fold normalizes tier configs to strings.
    const requiredTypes = new Set<string>()
    for (const tierVal of Object.values(selectedProfile.tiers)) {
      if (typeof tierVal === 'string') {
        const inst = installationsDict[tierVal]
        if (inst) {
          requiredTypes.add(inst.runnerType)
        } else {
          requiredTypes.add(tierVal)
        }
      }
    }

    // Group available installations by runner type
    const installationsByType: Record<string, { alias: string; binary: string }[]> = {}
    for (const rt of requiredTypes) {
      installationsByType[rt] = installations
        .filter(i => i.runnerType === rt && i.available)
        .map(i => ({ alias: i.alias, binary: i.binary }))
    }

    return {
      required_runner_types: [...requiredTypes].sort(),
      installations: installationsByType,
    }
  }, [profile, profiles, installations, installationsDict])

  // Auto-select installations when preflight changes
  useEffect(() => {
    if (!preflight) {
      setSelectedInstallations({})
      return
    }
    const selections: Record<string, string> = {}
    for (const rt of preflight.required_runner_types) {
      const insts = preflight.installations[rt] || []
      const defaultInst = insts.find(i => i.alias === `${rt}-default`)
      const first = insts[0]
      if (defaultInst) selections[rt] = defaultInst.alias
      else if (first) selections[rt] = first.alias
    }
    setSelectedInstallations(selections)
  }, [preflight])

  const installationsReady = preflight
    ? preflight.required_runner_types.every(rt => selectedInstallations[rt])
    : false

  const handleStart = async () => {
    const trimmedTask = task.trim()
    if (!trimmedTask) {
      setError('Please enter a task description')
      return
    }
    if (!profile) {
      setError('Please select a profile')
      return
    }
    if (!installationsReady) {
      setError('Please select an installation for each required runner type')
      return
    }
    setError(null)
    setLoading(true)
    try {
      const result = await api.startRun(
        trimmedTask, profile, scoutConcurrency, selectedInstallations, workflow,
      )
      if (!result.ok) {
        setError(result.message ?? 'Failed to start run')
      }
    } catch {
      setError('Network error')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="main-panel">
      <div className="phase-content">
        <div className="phase-inner">
          <h2 className="phase-heading">New Run</h2>

          <div className="launch-project-dir">
            <span className="launch-project-dir-label">PROJECT</span>
            <span className="launch-project-dir-path">{projectDir || '—'}</span>
          </div>

          {/* Workflow card */}
          <div className="card">
            <div className="launch-section-label">Workflow</div>
            <div className="launch-workflow-grid">
              <button
                className={`launch-workflow-card${workflow === 'plan' ? ' selected' : ''}`}
                onClick={() => setWorkflow('plan')}
              >
                <div className="launch-workflow-card-header">
                  <div className={`launch-radio-dot${workflow === 'plan' ? ' selected' : ''}`} />
                  <span className="launch-workflow-card-name">Plan</span>
                </div>
                <div className="launch-workflow-card-desc">Plan an approach, review it, then execute</div>
              </button>
              <button className="launch-workflow-card disabled" disabled>
                <div className="launch-workflow-card-header">
                  <div className="launch-radio-dot" />
                  <span className="launch-workflow-card-name">Milestones</span>
                  <span className="launch-badge-soon">coming soon</span>
                </div>
                <div className="launch-workflow-card-desc">Break work into milestones with phased delivery</div>
              </button>
            </div>
          </div>

          {/* Description card */}
          <div className="card">
            <div className="launch-section-label">Description</div>
            <div className="launch-description-hint">What should this run accomplish?</div>
            <textarea
              id="task-input"
              className="workflow-feedback"
              placeholder="Describe what you want to build..."
              rows={4}
              value={task}
              onChange={e => setTask(e.target.value)}
            />
          </div>

          {/* Configuration card */}
          <div className="card">
            <div className="launch-section-label">Configuration</div>

            {/* Profile */}
            <div className="launch-config-group">
              <div className="launch-config-label">Profile</div>
              <select
                id="profile-select"
                className="model-tier-select"
                value={profile}
                onChange={e => setProfile(e.target.value)}
              >
                {profiles.map(p => (
                  <option key={p.name} value={p.name}>
                    {p.name}
                    {p.readOnly ? ' (built-in)' : ''}
                  </option>
                ))}
              </select>
            </div>

            {/* Agent installations */}
            {preflight && preflight.required_runner_types.length > 0 && (
              <div className="launch-config-group">
                <div className="launch-config-label">Agent Installations</div>
                {preflight.required_runner_types.map(rt => {
                  const insts = preflight.installations[rt] || []
                  const selected = selectedInstallations[rt] || ''
                  return (
                    <div key={rt} className="launch-agent-row">
                      <span className="launch-agent-type">{rt}</span>
                      <div className={`launch-agent-status ${insts.length > 0 && selected ? 'available' : 'unavailable'}`} />
                      <select
                        className="launch-agent-select"
                        value={selected}
                        onChange={e => setSelectedInstallations(prev => ({ ...prev, [rt]: e.target.value }))}
                      >
                        <option value="">-- select --</option>
                        {insts.map(inst => (
                          <option key={inst.alias} value={inst.alias}>
                            {inst.alias} ({inst.binary})
                          </option>
                        ))}
                      </select>
                      {insts.length === 0 && (
                        <span className="launch-agent-missing">Not detected — configure in Settings</span>
                      )}
                    </div>
                  )
                })}
              </div>
            )}

            {/* Scout concurrency */}
            <div className="launch-config-group">
              <div className="launch-config-label">Scout Concurrency</div>
              <div className="launch-scouts-row">
                <input
                  id="scout-concurrency"
                  className="scout-concurrency-input"
                  type="number"
                  min={1}
                  max={32}
                  value={scoutConcurrency}
                  onChange={e => setScoutConcurrency(parseInt(e.target.value, 10) || 8)}
                />
                <span className="launch-scouts-hint">max parallel scout agents</span>
              </div>
            </div>
          </div>

          {error && <div className="no-runners-msg">{error}</div>}

          <div className="form-actions">
            <button
              id="btn-start-run"
              className="btn btn-primary"
              disabled={!hasRunners || loading || !installationsReady}
              title={
                !hasRunners
                  ? 'No available agent installations. Add and configure at least one in Settings.'
                  : undefined
              }
              onClick={handleStart}
            >
              {loading ? 'Starting...' : 'Start Run'}
            </button>
          </div>

          {!hasRunners && (
            <span className="no-runners-msg">
              No available agent installations. Open Settings to add and configure one.
            </span>
          )}
        </div>
      </div>
    </div>
  )
}
