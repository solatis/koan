import { useState, useEffect } from 'preact/hooks'
import { useStore } from '../store.js'

const TIERS = [
  {
    key: 'strong',
    label: 'Strong',
    description: 'Complex reasoning \u2014 intake analysis, task decomposition, orchestration, and planning. Requires deep understanding of requirements and codebase architecture.',
  },
  {
    key: 'standard',
    label: 'Standard',
    description: 'Implementation \u2014 executing planned changes based on well-specified work. Balances capability with cost for coding tasks.',
  },
  {
    key: 'cheap',
    label: 'Cheap',
    description: 'Narrow investigations \u2014 codebase scouting and targeted information gathering. Fast and cost-effective for focused questions.',
  },
]

function groupByProvider(models) {
  const groups = {}
  for (const m of models) {
    if (!groups[m.provider]) groups[m.provider] = []
    groups[m.provider].push(m)
  }
  // Sort providers alphabetically, models by name within each group
  return Object.keys(groups).sort().map(provider => ({
    provider,
    models: groups[provider].sort((a, b) => a.name.localeCompare(b.name)),
  }))
}

export function ModelConfig({ token, isGate = false, onClose }) {
  const pending = useStore(s => s.pendingInput)
  const availableModels = useStore(s => s.availableModels)
  const [tiers, setTiers] = useState({ strong: '', standard: '', cheap: '' })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  // Load current config on mount
  useEffect(() => {
    if (isGate && pending?.payload) {
      const t = pending.payload
      setTiers({
        strong: t?.strong || '',
        standard: t?.standard || '',
        cheap: t?.cheap || '',
      })
      setLoading(false)
      return
    }
    fetch(`/api/model-config?session=${encodeURIComponent(token)}`)
      .then(r => r.json())
      .then(data => {
        if (data.tiers) {
          setTiers({
            strong: data.tiers.strong || '',
            standard: data.tiers.standard || '',
            cheap: data.tiers.cheap || '',
          })
        }
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [])

  const handleSave = async () => {
    setSaving(true)
    const body = {
      tiers: {
        strong: tiers.strong || null,
        standard: tiers.standard || null,
        cheap: tiers.cheap || null,
      },
    }
    if (isGate && pending?.requestId) {
      body.requestId = pending.requestId
    }
    try {
      await fetch(`/api/model-config?session=${encodeURIComponent(token)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!isGate && onClose) onClose()
    } finally {
      setSaving(false)
    }
  }

  const grouped = groupByProvider(availableModels)

  if (loading) {
    return (
      <div class="phase-inner" style={{ paddingTop: '60px' }}>
        <div class="spinner" />
      </div>
    )
  }

  return (
    <div class="phase-inner">
      <h2 class="phase-heading">Model Configuration</h2>
      <p class="phase-status">
        Choose which models to use for each task type. Leave as &#x201C;Inherited&#x201D; to use the active model.
      </p>

      <div class="model-config-tiers">
        {TIERS.map(tier => (
          <div key={tier.key} class="model-tier-row">
            <div class="model-tier-header">
              <span class="model-tier-label">{tier.label}</span>
            </div>
            <p class="model-tier-description">{tier.description}</p>
            <select
              class="model-tier-select"
              value={tiers[tier.key]}
              onChange={e => setTiers(prev => ({ ...prev, [tier.key]: e.target.value }))}
            >
              <option value="">Inherited</option>
              {grouped.map(group => (
                <optgroup key={group.provider} label={group.provider}>
                  {group.models.map(m => (
                    <option key={m.id} value={m.id}>{m.name}</option>
                  ))}
                </optgroup>
              ))}
            </select>
          </div>
        ))}
      </div>

      <div class="form-actions">
        {!isGate && (
          <button class="btn btn-secondary" onClick={onClose}>Cancel</button>
        )}
        <button
          class="btn btn-primary"
          disabled={saving}
          onClick={handleSave}
        >
          {saving ? 'Saving...' : isGate ? 'Continue' : 'Save'}
        </button>
        {isGate && !tiers.strong && !tiers.standard && !tiers.cheap && (
          <span class="form-helper">All models will be inherited from the active model</span>
        )}
      </div>
    </div>
  )
}
