import { useState, useEffect } from 'react'
import { Profile } from '../store/index'
import * as api from '../api/client'

export function LandingPage() {
  const [task, setTask] = useState('')
  const [profile, setProfile] = useState('')
  const [scoutConcurrency, setScoutConcurrency] = useState(8)
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [hasRunners, setHasRunners] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Installation selection driven by profile
  const [preflight, setPreflight] = useState<api.StartRunPreflight | null>(null)
  const [preflightLoading, setPreflightLoading] = useState(false)
  const [selectedInstallations, setSelectedInstallations] = useState<Record<string, string>>({})

  useEffect(() => {
    Promise.all([api.getProfiles(), api.getProbe(), api.getInitialPrompt()]).then(
      ([profilesData, probeData, promptData]) => {
        setProfiles(profilesData.profiles)
        if (profilesData.profiles.length > 0) {
          setProfile(profilesData.profiles[0].name)
        }
        setHasRunners(probeData.runners.some(r => r.available))
        if (promptData.prompt) {
          setTask(promptData.prompt)
        }
      },
    )
  }, [])

  // Fetch preflight when profile changes
  useEffect(() => {
    if (!profile) {
      setPreflight(null)
      setSelectedInstallations({})
      return
    }
    setPreflightLoading(true)
    api.getStartRunPreflight(profile).then(data => {
      setPreflight(data)
      // Auto-select: prefer the active installation if valid, else first valid
      const selections: Record<string, string> = {}
      for (const [rt, insts] of Object.entries(data.installations)) {
        const active = insts.find(i => i.is_active && i.binary_valid)
        const firstValid = insts.find(i => i.binary_valid)
        if (active) selections[rt] = active.alias
        else if (firstValid) selections[rt] = firstValid.alias
      }
      setSelectedInstallations(selections)
      setPreflightLoading(false)
    }).catch(() => {
      setPreflight(null)
      setPreflightLoading(false)
    })
  }, [profile])

  // All required runner types must have a selected installation
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
        trimmedTask, profile, scoutConcurrency, selectedInstallations,
      )
      if (!result.ok) {
        setError(result.message ?? 'Failed to start run')
      }
      // The SSE 'phase' event will flip runStarted → live view renders
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

          <div className="question-card">
            <div className="question-header">Task</div>
            <textarea
              id="task-input"
              className="workflow-feedback"
              placeholder="Describe what you want to build..."
              rows={4}
              value={task}
              onChange={e => setTask(e.target.value)}
            />
          </div>

          <div className="model-config-section">
            <h3 className="model-config-section-heading">Profile</h3>
            <select
              id="profile-select"
              className="model-tier-select"
              value={profile}
              onChange={e => setProfile(e.target.value)}
            >
              {profiles.map(p => (
                <option key={p.name} value={p.name}>
                  {p.name}
                  {p.read_only ? ' (built-in)' : ''}
                </option>
              ))}
            </select>
          </div>

          {preflight && !preflightLoading && preflight.required_runner_types.length > 0 && (
            <div className="model-config-section">
              <h3 className="model-config-section-heading">Agent Installations</h3>
              {preflight.required_runner_types.map(rt => {
                const insts = preflight.installations[rt] || []
                const selected = selectedInstallations[rt] || ''
                const hasNoValid = insts.length > 0 && !insts.some(i => i.binary_valid)
                return (
                  <div key={rt} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                    <span style={{ minWidth: 70, fontWeight: 500 }}>{rt}</span>
                    <select
                      className="model-tier-select"
                      value={selected}
                      onChange={e => setSelectedInstallations(prev => ({...prev, [rt]: e.target.value}))}
                      style={{ flex: 1 }}
                    >
                      <option value="">-- select installation --</option>
                      {insts.map(inst => (
                        <option
                          key={inst.alias}
                          value={inst.alias}
                          disabled={!inst.binary_valid}
                        >
                          {inst.alias} ({inst.binary}){!inst.binary_valid ? ' ✘ missing' : ''}
                        </option>
                      ))}
                    </select>
                    {insts.length === 0 && (
                      <span className="no-runners-msg" style={{ fontSize: 13 }}>
                        No installations. Add one in Settings.
                      </span>
                    )}
                    {hasNoValid && (
                      <span className="no-runners-msg" style={{ fontSize: 13 }}>
                        All binaries missing. Update paths in Settings.
                      </span>
                    )}
                  </div>
                )
              })}
            </div>
          )}

          <div className="model-config-section">
            <h3 className="model-config-section-heading">Scout Concurrency</h3>
            <input
              id="scout-concurrency"
              className="scout-concurrency-input"
              type="number"
              min={1}
              max={32}
              value={scoutConcurrency}
              onChange={e => setScoutConcurrency(parseInt(e.target.value, 10) || 8)}
            />
          </div>

          {error && <div className="no-runners-msg">{error}</div>}

          <div className="form-actions">
            <button
              id="btn-start-run"
              className="btn btn-primary"
              disabled={!hasRunners || loading || !installationsReady}
              title={
                !hasRunners
                  ? 'No available runners. Install and authenticate at least one runner in Settings.'
                  : undefined
              }
              onClick={handleStart}
            >
              {loading ? 'Starting...' : 'Start Run'}
            </button>
          </div>

          {!hasRunners && (
            <span className="no-runners-msg">
              No available runners. Open Settings to install and authenticate a runner.
            </span>
          )}
        </div>
      </div>
    </div>
  )
}
