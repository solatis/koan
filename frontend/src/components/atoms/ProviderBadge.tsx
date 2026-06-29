/**
 * ProviderBadge -- a 30px rounded-square icon with a two-letter mono code
 * identifying a connection's provider type.
 *
 * Colors are decorative anchors; the two-letter code disambiguates. google
 * reuses an existing color value that is otherwise semantic -- acceptable,
 * since a badge is not a status read-out. openrouter uses #8a7e70 (deep warm
 * gray, hardcoded deliberately -- --status-queued was too light).
 *
 * Used in: ConnectionRow (Settings -> Connections) and optionally
 * ConnectionForm.
 */

import './ProviderBadge.css'

export type ProviderType =
  | 'anthropic'
  | 'openai'
  | 'google'
  | 'bedrock'
  | 'openrouter'
  | 'ollama-cloud'
  | 'voyage'

const CODES: Record<ProviderType, string> = {
  anthropic:     'AN',
  openai:        'OA',
  google:        'GO',
  bedrock:       'BE',
  openrouter:    'OR',
  'ollama-cloud': 'OC',
  voyage:        'VO',
}

interface ProviderBadgeProps {
  type: ProviderType
}

export function ProviderBadge({ type }: ProviderBadgeProps) {
  return (
    <span className={`atom-provider-badge atom-provider-badge--${type}`}>
      {CODES[type]}
    </span>
  )
}

export default ProviderBadge
