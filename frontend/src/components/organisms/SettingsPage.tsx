/**
 * SettingsPage — full-page settings view with all sections stacked.
 *
 * Presentational organism. All data and callbacks come from props.
 * The parent connects the store. Single centered scrollable column
 * matching the NewRunForm layout pattern.
 *
 * Sections: Profiles card, Providers card (M4: manage API keys and
 * non-secret config per provider), Runtime card.
 *
 * Used in: app shell settings route.
 */

import { useState, useRef, useEffect } from 'react'
import { EntityRow } from '../molecules/EntityRow'
import { InlineForm } from '../molecules/InlineForm'
import { FormRow } from '../molecules/FormRow'
// TabBar removed in M4: agent installation tabs deleted with the installation section.
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

// Installation interface removed in M4: agent installation concept deleted.

/** Presentational view of one provider's non-secret status and config. */
export interface ProviderConfigView {
  provider: string
  available: boolean
  region: string | null
  baseUrl: string | null
}

export interface SettingsPageProps {
  profiles: Profile[]
  onCreateProfile: (profile: Omit<Profile, 'id'>) => Promise<void>
  onUpdateProfile: (id: string, profile: Partial<Profile>) => Promise<void>
  onDeleteProfile: (id: string) => void

  // installations/runnerTypes/onCreateInstallation/onUpdateInstallation/
  // onDeleteInstallation/onDetectBinary removed in M4: installation concept deleted.

  providers: ProviderConfigView[]
  onSaveProvider: (provider: string, fields: { secret?: string; region?: string; baseUrl?: string }) => Promise<void>
  onDeleteProvider: (provider: string) => Promise<void>
  /**
   * Test connectivity and model listing for a provider with candidate form values.
   * Called pre-save; returns the green/red result payload. Never throws.
   */
  onTestProvider: (provider: string, fields: { secret?: string; region?: string; baseUrl?: string }) => Promise<{ ok: boolean; count?: number; message?: string }>

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

/**
 * Per-provider field policy: which optional fields are shown in the edit form.
 * bedrock requires a region and supports an endpoint; openai/anthropic support
 * an endpoint only; lmstudio is keyless and shows only the base URL;
 * google/voyage are key-only (matches backend brief D5).
 */
function providerFields(provider: string): { region: boolean; baseUrl: boolean } {
  if (provider === 'bedrock') return { region: true, baseUrl: true }
  if (provider === 'openai' || provider === 'anthropic') return { region: false, baseUrl: true }
  if (provider === 'lmstudio') return { region: false, baseUrl: true }
  return { region: false, baseUrl: false }
}

/** Providers for which the Test button is shown (model-listing capable). */
const LISTING_CAPABLE_PROVIDERS = new Set(['openai', 'anthropic', 'google', 'lmstudio'])

/** Build the non-secret config summary line for the EntityRow meta. */
function providerMeta(p: ProviderConfigView): string | undefined {
  const parts: string[] = []
  if (p.region) parts.push(`region: ${p.region}`)
  if (p.baseUrl) parts.push(`endpoint: ${p.baseUrl}`)
  return parts.length > 0 ? parts.join(' · ') : undefined
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
    // installations/runnerTypes/onCreateInstallation/onUpdateInstallation/
    // onDeleteInstallation/onDetectBinary removed in M4: installation concept deleted.
    providers, onSaveProvider, onDeleteProvider, onTestProvider,
    scoutConcurrency, onScoutConcurrencyChange,
    runnerOptions, modelOptionsForRunner, thinkingOptionsForModel,
  } = props

  // Inline form state -- only one open at a time across all cards
  const [editingProfileId, setEditingProfileId] = useState<string | null>(null)
  const [creatingProfile, setCreatingProfile] = useState(false)
  const [editingProvider, setEditingProvider] = useState<string | null>(null)

  // Auto-scroll to the active inline form when it opens
  const activeFormRef = useRef<HTMLDivElement>(null)
  const formOpen = editingProfileId || creatingProfile || editingProvider
  useEffect(() => {
    if (formOpen && activeFormRef.current) {
      activeFormRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }
  }, [formOpen, editingProfileId, creatingProfile, editingProvider])

  // Profile form fields
  const [pfName, setPfName] = useState('')
  const [pfTiers, setPfTiers] = useState<Record<string, TierConfig>>({
    strong: emptyTier(), standard: emptyTier(), cheap: emptyTier(),
  })

  // Provider form fields -- key is write-only, never pre-filled from stored value
  const [pvKey, setPvKey] = useState('')
  const [pvRegion, setPvRegion] = useState('')
  const [pvBaseUrl, setPvBaseUrl] = useState('')
  const [pvError, setPvError] = useState<string | null>(null)
  // Test connection state: 'idle' | 'testing' | 'ok' | 'fail'
  const [pvTestState, setPvTestState] = useState<'idle' | 'testing' | 'ok' | 'fail'>('idle')
  const [pvTestMsg, setPvTestMsg] = useState('')

  const closeAllForms = () => {
    setEditingProfileId(null)
    setCreatingProfile(false)
    setEditingProvider(null)
    setPvKey('')
    setPvRegion('')
    setPvBaseUrl('')
    setPvError(null)
    // Reset test result when form closes
    setPvTestState('idle')
    setPvTestMsg('')
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
      /* API error -- keep form open so user can retry */
    }
  }

  // Provider form helpers
  const openProviderEdit = (p: ProviderConfigView) => {
    closeAllForms()
    setEditingProvider(p.provider)
    // Pre-fill non-secret fields; key is always empty (write-only -- never returned by backend)
    setPvRegion(p.region ?? '')
    setPvBaseUrl(p.baseUrl ?? '')
    // Reset test result when opening a new provider form
    setPvTestState('idle')
    setPvTestMsg('')
  }

  /**
   * Save provider config. Builds a fields object that omits `secret` when the
   * user left the key input empty (preserves existing key). Requires a non-empty
   * region for bedrock client-side; also keeps the form open on a backend 422.
   */
  const saveProvider = async () => {
    if (!editingProvider) return
    const fields = providerFields(editingProvider)

    // Client-side bedrock region guard -- backend would return 422 but a
    // clear inline message is better UX than a thrown error.
    if (fields.region && !pvRegion.trim()) {
      setPvError('Region is required for bedrock')
      return
    }

    const body: { secret?: string; region?: string; baseUrl?: string } = {}
    if (pvKey.trim()) body.secret = pvKey.trim()
    if (fields.region) body.region = pvRegion.trim()
    if (fields.baseUrl) body.baseUrl = pvBaseUrl.trim()

    try {
      await onSaveProvider(editingProvider, body)
      closeAllForms()
    } catch (e) {
      // Backend 422 or other error: surface the message and keep the form open
      setPvError(e instanceof Error ? e.message : 'Failed to save provider config')
    }
  }

  /**
   * Build the same body as saveProvider and call onTestProvider with it.
   * Shows a green Badge on success or a red Badge on failure.
   */
  const testProvider = async () => {
    if (!editingProvider) return
    const fields = providerFields(editingProvider)
    const body: { secret?: string; region?: string; baseUrl?: string } = {}
    if (pvKey.trim()) body.secret = pvKey.trim()
    if (fields.region && pvRegion.trim()) body.region = pvRegion.trim()
    if (fields.baseUrl && pvBaseUrl.trim()) body.baseUrl = pvBaseUrl.trim()

    setPvTestState('testing')
    setPvTestMsg('')
    const result = await onTestProvider(editingProvider, body)
    if (result.ok) {
      setPvTestState('ok')
      setPvTestMsg(`Success! ${result.count ?? 0} models`)
    } else {
      setPvTestState('fail')
      setPvTestMsg(result.message ?? 'Failed')
    }
  }

  // Profile form content
  const profileFormContent = (
    <>
      <FormRow label="Name">
        {/* Profile rename requires delete + recreate -- not supported in current API */}
        <TextInput value={pfName} onChange={setPfName} placeholder="profile name" disabled={!!editingProfileId} />
      </FormRow>
      <TierFormRows tiers={pfTiers} onChange={handleTierChange} runnerOptions={runnerOptions} modelOptionsForRunner={modelOptionsForRunner} thinkingOptionsForModel={thinkingOptionsForModel} />
    </>
  )

  return (
    <div className="settings-page">
      <div className="settings-content">
        <h1 className="settings-title">Settings</h1>

        {/* === PROFILES === */}
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

        {/* === PROVIDERS === */}
        <div className="settings-card">
          <div className="settings-card-title">Providers</div>
          {providers.map(p => (
            <div key={p.provider}>
              <EntityRow
                name={p.provider}
                meta={providerMeta(p)}
                active={editingProvider === p.provider}
              >
                <span style={{ flex: 1 }} />
                <Badge variant={p.available ? 'success' : 'neutral'}>
                  {p.available ? 'configured' : 'not set'}
                </Badge>
                <Button variant="secondary" size="xs" onClick={() => openProviderEdit(p)}>Edit</Button>
                {(p.available || p.region || p.baseUrl) && (
                  <Button variant="danger" size="xs" onClick={() => onDeleteProvider(p.provider)}>Delete</Button>
                )}
              </EntityRow>
              {editingProvider === p.provider && (
                <div ref={activeFormRef}>
                  <InlineForm onSave={saveProvider} onCancel={closeAllForms}>
                    {/* lmstudio is keyless: hide API key field entirely */}
                    {p.provider !== 'lmstudio' && (
                      <FormRow label="API key">
                        <TextInput
                          value={pvKey}
                          onChange={setPvKey}
                          placeholder={p.available ? 'configured -- enter to replace' : 'enter API key'}
                        />
                      </FormRow>
                    )}
                    {providerFields(p.provider).region && (
                      <FormRow label="Region">
                        <TextInput
                          value={pvRegion}
                          onChange={setPvRegion}
                          placeholder="e.g. us-east-1"
                        />
                      </FormRow>
                    )}
                    {providerFields(p.provider).baseUrl && (
                      <FormRow label="Endpoint">
                        <TextInput
                          value={pvBaseUrl}
                          onChange={setPvBaseUrl}
                          placeholder={p.provider === 'lmstudio' ? 'http://localhost:1234/v1' : 'optional base URL override'}
                        />
                      </FormRow>
                    )}
                    {pvError && (
                      <div className="settings-provider-error">{pvError}</div>
                    )}
                    {/* Test button: only for listing-capable providers (not bedrock/voyage) */}
                    {LISTING_CAPABLE_PROVIDERS.has(p.provider) && (
                      <FormRow label="">
                        <Button
                          variant="secondary"
                          size="xs"
                          onClick={testProvider}
                          disabled={pvTestState === 'testing'}
                        >
                          {pvTestState === 'testing' ? 'Testing...' : 'Test connection'}
                        </Button>
                        {pvTestState === 'ok' && (
                          <Badge variant="success">{pvTestMsg}</Badge>
                        )}
                        {pvTestState === 'fail' && (
                          <Badge variant="error">Fail -- {pvTestMsg}</Badge>
                        )}
                      </FormRow>
                    )}
                  </InlineForm>
                </div>
              )}
            </div>
          ))}
        </div>

        {/* === RUNTIME === */}
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
