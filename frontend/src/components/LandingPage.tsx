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

  // Read from store (fed by SSE — always current, no API fetch needed)
  const profiles = useStore(s => s.configProfiles)
  const installations = useStore(s => s.configInstallations)
  const runners = useStore(s => s.configRunners)
  const storeScoutConcurrency = useStore(s => s.configScoutConcurrency)

  const hasRunners = runners.some(r => r.available)

  // Load initial prompt (one-shot, not config state)
  useEffect(() => {
    api.getInitialPrompt().then(data => {
      if (data.prompt) setTask(data.prompt)
    })
  }, [])

  // Auto-select first profile when profiles arrive from store
  useEffect(() => {
    if (profiles.length > 0 && !profile) {
      setProfile(profiles[0].name)
    }
  }, [profiles, profile])

  // Sync scout concurrency from store
  useEffect(() => {
    setScoutConcurrency(storeScoutConcurrency)
  }, [storeScoutConcurrency])

  // Derive preflight locally from store state (no API call)
  const preflight = useMemo(() => {
    const selectedProfile = profiles.find(p => p.name === profile)
    if (!selectedProfile) return null

    // Collect unique runner types from profile tiers
    const requiredTypes = new Set<string>()
    for (const tier of Object.values(selectedProfile.tiers)) {
      if (tier.runner_type) requiredTypes.add(tier.runner_type)
    }

    // Group installations by runner type with binary validity
    const installationsByType: Record<string, { alias: string; binary: string; binary_valid: boolean }[]> = {}
    for (const rt of requiredTypes) {
      installationsByType[rt] = installations
        .filter(i => i.runner_type === rt)
        .map(i => ({
          alias: i.alias,
          binary: i.binary,
          // We can't check binary existence client-side, but the start-run
          // endpoint validates. Show all installations as selectable.
          binary_valid: true,
        }))
    }

    return {
      required_runner_types: [...requiredTypes].sort(),
      installations: installationsByType,
    }
  }, [profile, profiles, installations])

  // Auto-select installations when preflight changes
  useEffect(() => {
    if (!preflight) {
      setSelectedInstallations({})
      return
    }
    const selections: Record<string, string> = {}
    for (const rt of preflight.required_runner_types) {
      const insts = preflight.installations[rt] || []
      // Prefer the {rt}-default installation, else first available
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
        trimmedTask, profile, scoutConcurrency, selectedInstallations,
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

          {preflight && preflight.required_runner_types.length > 0 && (
            <div className="model-config-section">
              <h3 className="model-config-section-heading">Agent Installations</h3>
              {preflight.required_runner_types.map(rt => {
                const insts = preflight.installations[rt] || []
                const selected = selectedInstallations[rt] || ''
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
                        <option key={inst.alias} value={inst.alias}>
                          {inst.alias} ({inst.binary})
                        </option>
                      ))}
                    </select>
                    {insts.length === 0 && (
                      <span className="no-runners-msg" style={{ fontSize: 13 }}>
                        No installations. Add one in Settings.
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
