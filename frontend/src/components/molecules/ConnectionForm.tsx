/**
 * ConnectionForm — provider connection add/edit form.
 *
 * Specialization of InlineForm. Fields are conditional on provider type.
 * Presentational: all data and actions come in via props.
 */

import './ConnectionForm.css'
import type { ReactNode } from 'react'
import { InlineForm } from './InlineForm'
import { FormRow } from './FormRow'
import { TextInput } from '../atoms/TextInput'
import { Select } from '../atoms/Select'
import { Button } from '../atoms/Button'
import { Badge } from '../atoms/Badge'
import type { ProviderType } from '../atoms/ProviderBadge'

export type { ProviderType }

export interface ConnectionDraft {
  type: ProviderType
  name: string
  apiKey: string // always '' in edit mode unless the user types
  region: string
  endpoint: string
}

export type TestState =
  | { kind: 'idle' }
  | { kind: 'pending' }
  | { kind: 'ok'; models: number }
  | { kind: 'error'; message: string }

const PROVIDER_LABELS: Record<ProviderType, string> = {
  anthropic: 'Anthropic',
  openai: 'OpenAI',
  google: 'Google',
  bedrock: 'AWS Bedrock',
  lmstudio: 'LM Studio (local)',
  voyage: 'Voyage',
}

const PROVIDER_OPTIONS = (Object.keys(PROVIDER_LABELS) as ProviderType[]).map(
  t => ({ value: t, label: PROVIDER_LABELS[t] }),
)

// Providers that expose a list-models endpoint, so a "Test connection" makes sense.
const LISTING_CAPABLE: ReadonlySet<ProviderType> = new Set<ProviderType>([
  'anthropic',
  'openai',
  'google',
  'lmstudio',
])

function HelperLine({ children }: { children: ReactNode }) {
  return <div className="conn-form__helper">{children}</div>
}

interface ConnectionFormProps {
  mode: 'add' | 'edit'
  draft: ConnectionDraft
  onChange: (draft: ConnectionDraft) => void
  onSave: () => void
  onCancel: () => void
  onDelete?: () => void
  onTest?: () => void
  testState?: TestState
  saving?: boolean
}

export function ConnectionForm({
  mode,
  draft,
  onChange,
  onSave,
  onCancel,
  onDelete,
  onTest,
  testState = { kind: 'idle' },
  saving = false,
}: ConnectionFormProps) {
  const set = (patch: Partial<ConnectionDraft>) => onChange({ ...draft, ...patch })

  // Switching provider in add mode resets the type-specific fields.
  const onProviderChange = (value: string) =>
    onChange({ ...draft, type: value as ProviderType, apiKey: '', region: '', endpoint: '' })

  // The "opt" tag is appended to the label string: FormRow's `label` is a plain
  // string and cannot carry a styled span. See the report flag.
  const apiKeyRow = (addPlaceholder: string) => (
    <FormRow label="API key">
      <TextInput
        mono
        value={draft.apiKey}
        onChange={v => set({ apiKey: v })}
        placeholder={mode === 'edit' ? 'configured — enter to replace' : addPlaceholder}
      />
    </FormRow>
  )

  const endpointRow = (placeholder: string, required = false) => (
    <FormRow label={required ? 'Endpoint' : 'Endpoint (opt)'}>
      <TextInput
        mono
        value={draft.endpoint}
        onChange={v => set({ endpoint: v })}
        placeholder={placeholder}
      />
    </FormRow>
  )

  const regionRow = () => (
    <FormRow label="Region">
      <TextInput value={draft.region} onChange={v => set({ region: v })} placeholder="us-east-1" />
    </FormRow>
  )

  const typeFields = (): ReactNode => {
    switch (draft.type) {
      case 'anthropic':
        return <>{apiKeyRow('sk-ant-...')}{endpointRow('base URL override')}</>
      case 'openai':
        return <>{apiKeyRow('sk-...')}{endpointRow('base URL override')}</>
      case 'google':
        return apiKeyRow('AIza...')
      case 'bedrock':
        return (
          <>
            {regionRow()}
            {endpointRow('base URL override')}
            <HelperLine>
              No API key field — Bedrock uses your AWS credential chain (env vars,
              shared profile, or IAM role).
            </HelperLine>
          </>
        )
      case 'lmstudio':
        return (
          <>
            {endpointRow('http://localhost:1234/v1', true)}
            <HelperLine>Keyless — a local OpenAI-compatible server.</HelperLine>
          </>
        )
      case 'voyage':
        return (
          <>
            {apiKeyRow('pa-...')}
            <HelperLine>
              Embedding provider — used by the Memory section, not by model roles.
            </HelperLine>
          </>
        )
    }
  }

  const showTest = LISTING_CAPABLE.has(draft.type) && !!onTest
  const showDelete = mode === 'edit' && !!onDelete
  const showExtraActions = showTest || showDelete

  return (
    <InlineForm onSave={onSave} onCancel={onCancel} saving={saving}>
      <div className="conn-form__header">
        {mode === 'add' ? 'New connection' : 'Edit connection'} · {PROVIDER_LABELS[draft.type]}
      </div>

      <FormRow label="Provider">
        <Select
          mono
          value={draft.type}
          onChange={onProviderChange}
          options={PROVIDER_OPTIONS}
          disabled={mode === 'edit'}
        />
      </FormRow>

      <FormRow label="Name">
        <TextInput
          mono
          value={draft.name}
          onChange={v => set({ name: v })}
          placeholder="connection id"
        />
      </FormRow>

      {typeFields()}

      {showExtraActions && (
        <div className="conn-form__extra-actions">
          {showTest && (
            <Button
              variant="teal"
              size="sm"
              onClick={onTest}
              disabled={testState.kind === 'pending'}
            >
              {testState.kind === 'pending' ? 'Testing…' : 'Test connection'}
            </Button>
          )}
          {testState.kind === 'ok' && <Badge variant="success">{testState.models} models</Badge>}
          {testState.kind === 'error' && <Badge variant="error">{testState.message}</Badge>}
          {showDelete && (
            <Button variant="danger" size="sm" onClick={onDelete} className="conn-form__delete">
              Delete connection
            </Button>
          )}
        </div>
      )}
    </InlineForm>
  )
}

export default ConnectionForm
