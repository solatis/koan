/**
 * ProviderBadge — a 30px rounded-square icon with a two-letter mono code
 * identifying a connection's provider type.
 *
 * Colors are decorative anchors; the two-letter code disambiguates. google
 * and lmstudio reuse existing color values that are otherwise semantic —
 * acceptable, since a badge is not a status read-out.
 *
 * Used in: ConnectionRow (Settings → Connections) and optionally
 * ConnectionForm.
 */

import './ProviderBadge.css'

export type ProviderType =
  | 'anthropic'
  | 'openai'
  | 'google'
  | 'bedrock'
  | 'lmstudio'
  | 'voyage'

const CODES: Record<ProviderType, string> = {
  anthropic: 'AN',
  openai: 'OA',
  google: 'GO',
  bedrock: 'BE',
  lmstudio: 'LM',
  voyage: 'VO',
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
