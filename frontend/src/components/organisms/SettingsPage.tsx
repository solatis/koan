/**
 * SettingsPage — full-page settings view with all sections stacked.
 *
 * Presentational organism. All data and callbacks come from props.
 * The parent connects the store. Single centered scrollable column
 * matching the NewRunForm layout pattern.
 *
 * Used in: app shell, replaces SettingsOverlay for the new design.
 */

import { useState, useRef, useEffect } from 'react'
import { EntityRow } from '../molecules/EntityRow'
import { InlineForm } from '../molecules/InlineForm'
import { FormRow } from '../molecules/FormRow'
import { TabBar } from '../molecules/TabBar'
import { SettingRow } from '../molecules/SettingRow'
import { TextInput } from '../atoms/TextInput'
import { Select } from '../atoms/Select'
import { NumberInput } from '../atoms/NumberInput'
import { Button } from '../atoms/Button'
import { Badge } from '../atoms/Badge'
import './SettingsPage.css'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TierConfig {
  runner: string
  model: string
  thinking: string
}

export interface Profile {
  id: string
  name: string
  locked?: boolean
  tiers: { strong: TierConfig; standard: TierConfig; cheap: TierConfig }
}

export interface Installation {
  id: string
  alias: string
  runner: string
  binary: string
  extraArgs?: string
  isDefault?: boolean
  available?: boolean
}

export interface SettingsPageProps {
  profiles: Profile[]
  onCreateProfile: (profile: Omit<Profile, 'id'>) => Promise<void>
  onUpdateProfile: (id: string, profile: Partial<Profile>) => Promise<void>
  onDeleteProfile: (id: string) => void

  installations: Installation[]
  runnerTypes: string[]
  onCreateInstallation: (install: Omit<Installation, 'id'>) => Promise<void>
  onUpdateInstallation: (id: string, install: Partial<Installation>) => Promise<void>
  onDeleteInstallation: (id: string) => void
  onDetectBinary: (runner: string) => Promise<string | null>

  scoutConcurrency: number
  onScoutConcurrencyChange: (n: number) => void

  runnerOptions: { value: string; label: string }[]
  modelOptionsForRunner: (runner: string) => { value: string; label: string }[]
  thinkingOptionsForModel: (runner: string, model: string) => { value: string; label: string }[]
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const TIER_KEYS = ['strong', 'standard', 'cheap'] as const

function tierSummary(tiers: Profile['tiers']): string {
  return TIER_KEYS.map(k => `${k}: ${tiers[k].runner}`).join(' · ')
}

function emptyTier(): TierConfig {
  return { runner: '', model: '', thinking: '' }
}

// ---------------------------------------------------------------------------
// Profile tier form rows
// ---------------------------------------------------------------------------

function TierFormRows({
  tiers, onChange, runnerOptions, modelOptionsForRunner, thinkingOptionsForModel,
}: {
  tiers: Record<string, TierConfig>
  onChange: (tier: string, field: keyof TierConfig, value: string) => void
  runnerOptions: { value: string; label: string }[]
  modelOptionsForRunner: (runner: string) => { value: string; label: string }[]
  thinkingOptionsForModel: (runner: string, model: string) => { value: string; label: string }[]
}) {
  return (
    <>
      {TIER_KEYS.map(tier => (
        <FormRow key={tier} label={tier.charAt(0).toUpperCase() + tier.slice(1)}>
          <Select value={tiers[tier].runner} onChange={v => onChange(tier, 'runner', v)} options={runnerOptions} mono placeholder="— runner —" />
          <Select value={tiers[tier].model} onChange={v => onChange(tier, 'model', v)} options={modelOptionsForRunner(tiers[tier].runner)} mono placeholder="— model —" />
          <Select value={tiers[tier].thinking} onChange={v => onChange(tier, 'thinking', v)} options={thinkingOptionsForModel(tiers[tier].runner, tiers[tier].model)} mono placeholder="— thinking —" />
        </FormRow>
      ))}
    </>
  )
}

// ---------------------------------------------------------------------------
// SettingsPage
// ---------------------------------------------------------------------------

export function SettingsPage(props: SettingsPageProps) {
  const {
    profiles, onCreateProfile, onUpdateProfile, onDeleteProfile,
    installations, runnerTypes, onCreateInstallation, onUpdateInstallation, onDeleteInstallation, onDetectBinary,
    scoutConcurrency, onScoutConcurrencyChange,
    runnerOptions, modelOptionsForRunner, thinkingOptionsForModel,
  } = props

  // Agents tab
  const [activeTab, setActiveTab] = useState(runnerTypes[0] || '')

  // Inline form state — only one open at a time across all sections
  const [editingProfileId, setEditingProfileId] = useState<string | null>(null)
  const [editingInstallationId, setEditingInstallationId] = useState<string | null>(null)
  const [creatingProfile, setCreatingProfile] = useState(false)
  const [creatingInstallation, setCreatingInstallation] = useState(false)

  // Auto-scroll to the active inline form when it opens
  const activeFormRef = useRef<HTMLDivElement>(null)
  const formOpen = editingProfileId || editingInstallationId || creatingProfile || creatingInstallation
  useEffect(() => {
    if (formOpen && activeFormRef.current) {
      activeFormRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }
  }, [formOpen, editingProfileId, editingInstallationId, creatingProfile, creatingInstallation])

  // Profile form fields
  const [pfName, setPfName] = useState('')
  const [pfTiers, setPfTiers] = useState<Record<string, TierConfig>>({
    strong: emptyTier(), standard: emptyTier(), cheap: emptyTier(),
  })

  // Installation form fields
  const [ifAlias, setIfAlias] = useState('')
  const [ifRunner, setIfRunner] = useState('')
  const [ifBinary, setIfBinary] = useState('')
  const [ifExtra, setIfExtra] = useState('')

  const closeAllForms = () => {
    setEditingProfileId(null)
    setEditingInstallationId(null)
    setCreatingProfile(false)
    setCreatingInstallation(false)
  }

  const switchTab = (tab: string) => {
    closeAllForms()
    setActiveTab(tab)
  }

  // Profile form helpers
  const openProfileEdit = (p: Profile) => {
    closeAllForms()
    setEditingProfileId(p.id)
    setPfName(p.name)
    setPfTiers({ ...p.tiers })
  }

  const openProfileCreate = () => {
    closeAllForms()
    setCreatingProfile(true)
    setPfName('')
    setPfTiers({ strong: emptyTier(), standard: emptyTier(), cheap: emptyTier() })
  }

  const handleTierChange = (tier: string, field: keyof TierConfig, value: string) => {
    setPfTiers(prev => ({ ...prev, [tier]: { ...prev[tier], [field]: value } }))
  }

  const saveProfile = async () => {
    const data = { name: pfName, tiers: pfTiers as Profile['tiers'] }
    try {
      if (editingProfileId) await onUpdateProfile(editingProfileId, data)
      else await onCreateProfile(data)
      closeAllForms()
    } catch {
      /* API error — keep form open so user can retry */
    }
  }

  // Installation form helpers
  const openInstallEdit = (inst: Installation) => {
    closeAllForms()
    setEditingInstallationId(inst.id)
    setIfAlias(inst.alias)
    setIfRunner(inst.runner)
    setIfBinary(inst.binary)
    setIfExtra(inst.extraArgs || '')
  }

  const openInstallCreate = () => {
    closeAllForms()
    setCreatingInstallation(true)
    setIfAlias('')
    setIfRunner(activeTab)
    setIfBinary('')
    setIfExtra('')
  }

  const saveInstallation = async () => {
    const data = { alias: ifAlias, runner: ifRunner, binary: ifBinary, extraArgs: ifExtra }
    try {
      if (editingInstallationId) await onUpdateInstallation(editingInstallationId, data)
      else await onCreateInstallation(data)
      closeAllForms()
    } catch {
      /* API error — keep form open so user can retry */
    }
  }

  // Shared form content
  const profileFormContent = (
    <>
      <FormRow label="Name">
        {/* Profile rename requires delete + recreate — not supported in current API */}
        <TextInput value={pfName} onChange={setPfName} placeholder="profile name" disabled={!!editingProfileId} />
      </FormRow>
      <TierFormRows tiers={pfTiers} onChange={handleTierChange} runnerOptions={runnerOptions} modelOptionsForRunner={modelOptionsForRunner} thinkingOptionsForModel={thinkingOptionsForModel} />
    </>
  )

  const installFormContent = (
    <>
      <FormRow label="Alias">
        {/* Installation alias is the API identifier — not editable on update */}
        <TextInput value={ifAlias} onChange={setIfAlias} placeholder="installation name" disabled={!!editingInstallationId} />
      </FormRow>
      <FormRow label="Runner">
        <Select value={ifRunner} onChange={setIfRunner} options={runnerOptions} mono />
      </FormRow>
      <FormRow label="Binary">
        <TextInput value={ifBinary} onChange={setIfBinary} mono />
        <Button variant="teal" size="sm" onClick={async () => {
          const path = await onDetectBinary(ifRunner)
          if (path) setIfBinary(path)
        }}>Detect</Button>
      </FormRow>
      <FormRow label="Extra args">
        <TextInput value={ifExtra} onChange={setIfExtra} mono />
      </FormRow>
    </>
  )

  const tabInstallations = installations.filter(i => i.runner === activeTab)

  return (
    <div className="settings-page">
      <div className="settings-content">
        <h1 className="settings-title">Settings</h1>

        {/* ═══ PROFILES ═══ */}
        <div className="settings-card">
          <div className="settings-card-title">Profiles</div>
          {profiles.map(p => (
            <div key={p.id}>
              <EntityRow name={p.name} meta={tierSummary(p.tiers)} active={editingProfileId === p.id}>
                {p.locked ? (
                  <Badge variant="neutral">locked</Badge>
                ) : (
                  <>
                    <span style={{ flex: 1 }} />
                    <Button variant="secondary" size="xs" onClick={() => openProfileEdit(p)}>Edit</Button>
                    <Button variant="danger" size="xs" onClick={() => onDeleteProfile(p.id)}>Delete</Button>
                  </>
                )}
              </EntityRow>
              {editingProfileId === p.id && (
                <div ref={activeFormRef}>
                  <InlineForm onSave={saveProfile} onCancel={closeAllForms}>{profileFormContent}</InlineForm>
                </div>
              )}
            </div>
          ))}
          {creatingProfile && (
            <div ref={activeFormRef}>
              <InlineForm onSave={saveProfile} onCancel={closeAllForms}>{profileFormContent}</InlineForm>
            </div>
          )}
          <div className="settings-add-trigger">
            <Button variant="text" onClick={openProfileCreate}>+ New profile</Button>
          </div>
        </div>

        {/* ═══ AGENT INSTALLATIONS ═══ */}
        <div className="settings-card">
          <div className="settings-card-title">Agent Installations</div>
          <TabBar tabs={runnerTypes} activeTab={activeTab} onChange={switchTab} />
          {tabInstallations.map(inst => (
            <div key={inst.id}>
              <EntityRow name={inst.alias} mono meta={inst.binary + (inst.extraArgs ? ' ' + inst.extraArgs : '')} active={editingInstallationId === inst.id}>
                {inst.isDefault && <Badge variant="default">default</Badge>}
                {inst.available ? <Badge variant="success">available</Badge> : <Badge variant="error">unavailable</Badge>}
                <span style={{ flex: 1 }} />
                <Button variant="secondary" size="xs" onClick={() => openInstallEdit(inst)}>Edit</Button>
                {!inst.isDefault && <Button variant="danger" size="xs" onClick={() => onDeleteInstallation(inst.id)}>Delete</Button>}
              </EntityRow>
              {editingInstallationId === inst.id && (
                <div ref={activeFormRef}>
                  <InlineForm onSave={saveInstallation} onCancel={closeAllForms}>{installFormContent}</InlineForm>
                </div>
              )}
            </div>
          ))}
          {creatingInstallation && (
            <div ref={activeFormRef}>
              <InlineForm onSave={saveInstallation} onCancel={closeAllForms}>{installFormContent}</InlineForm>
            </div>
          )}
          <div className="settings-add-trigger">
            <Button variant="text" onClick={openInstallCreate}>+ Add {activeTab} installation</Button>
          </div>
        </div>

        {/* ═══ RUNTIME ═══ */}
        <div className="settings-card">
          <div className="settings-card-title">Runtime</div>
          <SettingRow label="Scout concurrency" description="Maximum number of parallel scout agents">
            <NumberInput value={scoutConcurrency} onChange={onScoutConcurrencyChange} min={1} max={32} />
          </SettingRow>
        </div>
      </div>
    </div>
  )
}

export default SettingsPage
