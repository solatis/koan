import { useState, useEffect } from 'react'
import { useStore, Installation } from '../store/index'
import { tierSummary } from '../utils'
import * as api from '../api/client'
import { RunnerInfo } from '../api/client'

// -- Cascade dropdowns helpers ------------------------------------------------

type TierConfig = { runner_type: string; model: string; thinking: string }
type TierMap = Record<string, TierConfig>

const TIER_NAMES = ['strong', 'standard', 'cheap'] as const

function getModelsForRunner(runners: RunnerInfo[], rt: string) {
  return runners.find(r => r.runner_type === rt)?.models ?? []
}

function getThinkingModes(runners: RunnerInfo[], rt: string, model: string) {
  const models = getModelsForRunner(runners, rt)
  return models.find(m => m.alias === model)?.thinking_modes ?? []
}

// -- ProfileForm --------------------------------------------------------------

function ProfileForm({
  initialName,
  initialRunnerType,   // best-effort from stored tier string
  isEdit,
  runners,
  onSave,
  onCancel,
}: {
  initialName: string
  initialRunnerType: string  // pre-populate runner dropdown when editing
  isEdit: boolean
  runners: RunnerInfo[]
  onSave: () => void
  onCancel: () => void
}) {
  const [name, setName] = useState(initialName)
  const [tiers, setTiers] = useState<TierMap>(() => {
    const t: TierMap = {}
    for (const tier of TIER_NAMES) {
      t[tier] = { runner_type: tier === 'strong' ? initialRunnerType : '', model: '', thinking: '' }
    }
    return t
  })
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  const setTierField = (tier: string, field: keyof TierConfig, value: string) => {
    setTiers(prev => {
      const updated = { ...prev[tier], [field]: value }
      if (field === 'runner_type') {
        updated.model = ''
        updated.thinking = ''
      }
      if (field === 'model') {
        updated.thinking = ''
      }
      return { ...prev, [tier]: updated }
    })
  }

  const handleSave = async () => {
    if (!isEdit && !name.trim()) {
      setFormError('Profile name is required')
      return
    }
    const filteredTiers: TierMap = {}
    for (const tier of TIER_NAMES) {
      const t = tiers[tier]
      if (t.runner_type && t.model) {
        filteredTiers[tier] = t
      }
    }
    setSaving(true)
    try {
      const res = isEdit
        ? await api.updateProfile(name, filteredTiers)
        : await api.createProfile(name.trim(), filteredTiers)
      if (res.ok) {
        onSave()
      } else {
        setFormError(res.message ?? 'Failed to save profile')
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="profile-form">
      {!isEdit && (
        <div className="tier-form-row">
          <span className="tier-form-label">Name</span>
          <input
            className="model-tier-input"
            style={{ flex: 1 }}
            placeholder="profile name"
            value={name}
            onChange={e => setName(e.target.value)}
          />
        </div>
      )}
      {TIER_NAMES.map(tier => {
        const t = tiers[tier]
        const models = getModelsForRunner(runners, t.runner_type)
        const thinkingModes = getThinkingModes(runners, t.runner_type, t.model)
        return (
          <div key={tier} className="tier-form-row">
            <span className="tier-form-label">{tier}</span>
            <select
              className="model-tier-select"
              value={t.runner_type}
              onChange={e => setTierField(tier, 'runner_type', e.target.value)}
              style={{ flex: 1 }}
            >
              <option value="">-- runner --</option>
              {runners.map(r => (
                <option key={r.runner_type} value={r.runner_type}>
                  {r.runner_type}
                </option>
              ))}
            </select>
            <select
              className="model-tier-select"
              value={t.model}
              onChange={e => setTierField(tier, 'model', e.target.value)}
              style={{ flex: 1 }}
              disabled={!t.runner_type}
            >
              <option value="">-- model --</option>
              {models.map(m => (
                <option key={m.alias} value={m.alias}>
                  {m.display_name || m.alias}
                </option>
              ))}
            </select>
            <select
              className="model-tier-select"
              value={t.thinking}
              onChange={e => setTierField(tier, 'thinking', e.target.value)}
              style={{ flex: 1 }}
              disabled={!t.model}
            >
              <option value="">-- thinking --</option>
              {thinkingModes.map(tm => (
                <option key={tm} value={tm}>
                  {tm}
                </option>
              ))}
            </select>
          </div>
        )
      })}
      {formError && <div className="no-runners-msg">{formError}</div>}
      <div className="form-actions" style={{ marginTop: 12 }}>
        <button className="btn btn-secondary" onClick={onCancel} disabled={saving}>
          Cancel
        </button>
        <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
          {saving ? 'Saving...' : 'Save'}
        </button>
      </div>
    </div>
  )
}

// -- InstallationForm ---------------------------------------------------------

function InstallationForm({
  initialAlias,
  initialRunnerType,
  initialBinary,
  initialExtraArgs,
  isEdit,
  allRunners,
  onSave,
  onCancel,
}: {
  initialAlias: string
  initialRunnerType: string
  initialBinary: string
  initialExtraArgs: string[]
  isEdit: boolean
  allRunners: RunnerInfo[]
  onSave: () => void
  onCancel: () => void
}) {
  const [alias, setAlias] = useState(initialAlias)
  const [runnerType, setRunnerType] = useState(initialRunnerType)
  const [binary, setBinary] = useState(initialBinary)
  const [extraArgs, setExtraArgs] = useState(initialExtraArgs.join(' '))
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  const handleDetect = async () => {
    if (!runnerType) {
      setFormError('Select a runner type first')
      return
    }
    const res = await api.detectAgent(runnerType)
    if (res.path) {
      setBinary(res.path)
    } else {
      setFormError('Binary not found in PATH')
    }
  }

  const handleSave = async () => {
    if (!alias.trim()) {
      setFormError('Alias is required')
      return
    }
    const args = extraArgs.trim() ? extraArgs.trim().split(/\s+/) : []
    setSaving(true)
    try {
      const res = isEdit
        ? await api.updateAgent(alias, {
            runner_type: runnerType,
            binary: binary.trim(),
            extra_args: args,
          })
        : await api.createAgent({
            alias: alias.trim(),
            runner_type: runnerType,
            binary: binary.trim(),
            extra_args: args,
          })
      if (res.ok) {
        onSave()
      } else {
        setFormError(res.message ?? 'Failed to save installation')
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="profile-form">
      {!isEdit && (
        <div className="tier-form-row">
          <span className="tier-form-label">Alias</span>
          <input
            className="model-tier-input"
            style={{ flex: 1 }}
            placeholder="my-claude"
            value={alias}
            onChange={e => setAlias(e.target.value)}
          />
        </div>
      )}
      <div className="tier-form-row">
        <span className="tier-form-label">Runner</span>
        <select
          className="model-tier-select"
          style={{ flex: 1 }}
          value={runnerType}
          onChange={e => setRunnerType(e.target.value)}
        >
          <option value="">-- runner type --</option>
          {allRunners.map(r => (
            <option key={r.runner_type} value={r.runner_type}>
              {r.runner_type}
            </option>
          ))}
        </select>
      </div>
      <div className="tier-form-row">
        <span className="tier-form-label">Binary</span>
        <input
          className="model-tier-input"
          style={{ flex: 1 }}
          placeholder="/usr/local/bin/claude"
          value={binary}
          onChange={e => setBinary(e.target.value)}
        />
        <button
          className="btn btn-secondary"
          style={{ padding: '4px 10px', fontSize: 13 }}
          onClick={handleDetect}
        >
          Detect
        </button>
      </div>
      <div className="tier-form-row">
        <span className="tier-form-label">Extra args</span>
        <input
          className="model-tier-input"
          style={{ flex: 1 }}
          placeholder="--verbose"
          value={extraArgs}
          onChange={e => setExtraArgs(e.target.value)}
        />
      </div>
      {formError && <div className="no-runners-msg">{formError}</div>}
      <div className="form-actions" style={{ marginTop: 12 }}>
        <button className="btn btn-secondary" onClick={onCancel} disabled={saving}>
          Cancel
        </button>
        <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
          {saving ? 'Saving...' : 'Save'}
        </button>
      </div>
    </div>
  )
}

// -- Main overlay -------------------------------------------------------------

export function SettingsOverlay() {
  const setSettingsOpen = useStore(s => s.setSettingsOpen)

  // Read all config from the store (fed by SSE events — always current)
  const profilesDict = useStore(s => s.settings.profiles)
  const installationsDict = useStore(s => s.settings.installations)
  const scoutConcurrency = useStore(s => s.settings.defaultScoutConcurrency)

  const profiles = Object.values(profilesDict)
  const installations = Object.values(installationsDict)

  // Probe runner info is not in the projection store (only availability flags
  // are stored). Fetch it once on open for the profile/installation forms.
  const [runners, setRunners] = useState<RunnerInfo[]>([])
  useEffect(() => {
    api.getProbeInfo().then(data => setRunners(data.runners ?? []))
  }, [])

  const availableRunners = runners.filter(r => r.available)

  // Local UI state for forms
  const [localScoutConcurrency, setLocalScoutConcurrency] = useState(scoutConcurrency)
  const [showNewProfile, setShowNewProfile] = useState(false)
  const [editingProfile, setEditingProfile] = useState<string | null>(null)
  const [showNewInstallation, setShowNewInstallation] = useState(false)
  const [editingInstallation, setEditingInstallation] = useState<string | null>(null)
  const [activeRunnerTab, setActiveRunnerTab] = useState<string | null>(null)

  // Sync local scout concurrency when store changes
  useEffect(() => {
    setLocalScoutConcurrency(scoutConcurrency)
  }, [scoutConcurrency])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSettingsOpen(false)
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [setSettingsOpen])

  const handleDeleteProfile = async (name: string) => {
    await api.deleteProfile(name)
    // SSE event updates the store automatically
  }

  const handleDeleteInstallation = async (alias: string) => {
    await api.deleteAgent(alias)
  }

  const handleSaveScoutConcurrency = async () => {
    await api.saveScoutConcurrency(localScoutConcurrency)
  }

  // Group installations by runner type
  const installationsByType: Record<string, Installation[]> = {}
  for (const inst of installations) {
    if (!installationsByType[inst.runnerType]) {
      installationsByType[inst.runnerType] = []
    }
    installationsByType[inst.runnerType].push(inst)
  }
  const runnerTypes = Object.keys(installationsByType).sort()

  // Auto-select first tab when runner types arrive
  const currentTab = activeRunnerTab && runnerTypes.includes(activeRunnerTab)
    ? activeRunnerTab
    : runnerTypes[0] ?? null
  const currentTabInstallations = currentTab ? installationsByType[currentTab] ?? [] : []

  const editingProfileData = editingProfile ? profilesDict[editingProfile] : null
  const editingInstData = editingInstallation ? installationsDict[editingInstallation] : null

  return (
    <div className="settings-overlay">
      <div className="settings-overlay-backdrop" onClick={() => setSettingsOpen(false)}>
        <div className="settings-overlay-panel" onClick={e => e.stopPropagation()}>
          <div className="settings-overlay-header">
            <span className="settings-overlay-title">Settings</span>
            <button
              className="settings-btn"
              id="btn-close-settings"
              aria-label="Close"
              onClick={() => setSettingsOpen(false)}
            >
              &#10005;
            </button>
          </div>

          <div className="settings-overlay-body">
            {/* Profiles */}
            <div className="settings-section-heading">Profiles</div>
            {profiles.map(p => (
              <div key={p.name} className="profile-row">
                <span className="profile-row-name">
                  {p.name}
                  {p.readOnly && ' [locked]'}
                </span>
                <span className="profile-row-tiers">
                  {tierSummary(p.tiers)}
                </span>
                {!p.readOnly && (
                  <span className="profile-row-actions">
                    <button
                      className="btn btn-secondary"
                      style={{ padding: '4px 10px', fontSize: 13 }}
                      onClick={() => {
                        setShowNewProfile(false)
                        setEditingProfile(p.name)
                      }}
                    >
                      Edit
                    </button>
                    <button
                      className="btn btn-secondary"
                      style={{ padding: '4px 10px', fontSize: 13 }}
                      onClick={() => handleDeleteProfile(p.name)}
                    >
                      Delete
                    </button>
                  </span>
                )}
              </div>
            ))}

            {editingProfile && editingProfileData && (
              <ProfileForm
                initialName={editingProfile}
                initialRunnerType={Object.values(editingProfileData.tiers)[0] ?? ''}
                isEdit
                runners={availableRunners}
                onSave={() => setEditingProfile(null)}
                onCancel={() => setEditingProfile(null)}
              />
            )}

            {!showNewProfile ? (
              <button
                className="btn btn-secondary"
                style={{ marginTop: 8 }}
                onClick={() => {
                  setEditingProfile(null)
                  setShowNewProfile(true)
                }}
              >
                + New Profile
              </button>
            ) : (
              <ProfileForm
                initialName=""
                initialRunnerType=""
                isEdit={false}
                runners={availableRunners}
                onSave={() => setShowNewProfile(false)}
                onCancel={() => setShowNewProfile(false)}
              />
            )}

            {/* Agent Installations — tabbed by runner type */}
            <div className="settings-section-heading" style={{ marginTop: 24 }}>
              Agent Installations
            </div>

            {runnerTypes.length > 0 && (
              <div>
                {/* Tab bar */}
                <div className="install-tab-bar">
                  {runnerTypes.map(rt => (
                    <button
                      key={rt}
                      className={`install-tab${rt === currentTab ? ' install-tab--active' : ''}`}
                      onClick={() => setActiveRunnerTab(rt)}
                    >
                      {rt}
                    </button>
                  ))}
                </div>

                {/* Tab content */}
                {currentTab && (
                  <div className="install-tab-content">
                    {currentTabInstallations.map(inst => {
                      const isDefault = inst.alias === `${currentTab}-default`
                      return (
                        <div
                          key={inst.alias}
                          className={`install-row${isDefault ? ' install-row--default' : ''}`}
                        >
                          <div className="install-row-info">
                            <span className="install-row-alias">{inst.alias}</span>
                            {isDefault && <span className="install-row-badge">default</span>}
                            {inst.available && <span className="install-row-badge">available</span>}
                          </div>
                          <span className="install-row-path">
                            {inst.binary || '--'}
                            {inst.extraArgs && inst.extraArgs.length > 0 && ` ${inst.extraArgs.join(' ')}`}
                          </span>
                          <span className="profile-row-actions">
                            <button
                              className="btn btn-secondary"
                              style={{ padding: '4px 10px', fontSize: 13 }}
                              onClick={() => {
                                setShowNewInstallation(false)
                                setEditingInstallation(inst.alias)
                              }}
                            >
                              Edit
                            </button>
                            {!isDefault && (
                              <button
                                className="btn btn-secondary btn-danger"
                                style={{ padding: '4px 10px', fontSize: 13 }}
                                onClick={() => handleDeleteInstallation(inst.alias)}
                              >
                                Delete
                              </button>
                            )}
                          </span>
                        </div>
                      )
                    })}

                    {editingInstallation && editingInstData && editingInstData.runnerType === currentTab && (
                      <InstallationForm
                        initialAlias={editingInstallation}
                        initialRunnerType={editingInstData.runnerType}
                        initialBinary={editingInstData.binary}
                        initialExtraArgs={editingInstData.extraArgs}
                        isEdit
                        allRunners={runners}
                        onSave={() => setEditingInstallation(null)}
                        onCancel={() => setEditingInstallation(null)}
                      />
                    )}

                    {!showNewInstallation ? (
                      <button
                        className="install-add-btn"
                        onClick={() => {
                          setEditingInstallation(null)
                          setShowNewInstallation(true)
                        }}
                      >
                        + Add {currentTab} installation
                      </button>
                    ) : (
                      <InstallationForm
                        initialAlias=""
                        initialRunnerType={currentTab}
                        initialBinary=""
                        initialExtraArgs={[]}
                        isEdit={false}
                        allRunners={runners}
                        onSave={() => setShowNewInstallation(false)}
                        onCancel={() => setShowNewInstallation(false)}
                      />
                    )}
                  </div>
                )}
              </div>
            )}

            {/* Scout Concurrency */}
            <div className="model-config-section" style={{ marginTop: 24 }}>
              <div className="settings-section-heading">Scout Concurrency</div>
              <div
                style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 8 }}
              >
                <input
                  id="settings-scout-concurrency"
                  className="scout-concurrency-input"
                  type="number"
                  min={1}
                  max={32}
                  value={localScoutConcurrency}
                  onChange={e =>
                    setLocalScoutConcurrency(parseInt(e.target.value, 10) || 8)
                  }
                />
                <button
                  className="btn btn-secondary"
                  style={{ padding: '4px 12px', fontSize: 13 }}
                  onClick={handleSaveScoutConcurrency}
                >
                  Save
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
