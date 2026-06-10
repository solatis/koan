/**
 * ConnectionRow — a two-line list item for a provider connection.
 *
 * Parallels EntityRow but with a leading ProviderBadge. Used in the
 * Settings → Connections section, one per connection, with the active
 * row's ConnectionForm rendered inline below it by the parent.
 */

import './ConnectionRow.css'
import { ProviderBadge, type ProviderType } from '../atoms/ProviderBadge'
import { Badge } from '../atoms/Badge'
import { Button } from '../atoms/Button'

interface ConnectionRowProps {
  type: ProviderType
  id: string
  meta: string
  status: 'configured' | 'not-set'
  active?: boolean
  onEdit: () => void
}

export function ConnectionRow({ type, id, meta, status, active = false, onEdit }: ConnectionRowProps) {
  return (
    <div className={`mol-connection-row${active ? ' mol-connection-row--active' : ''}`}>
      <ProviderBadge type={type} />
      <div className="mol-connection-row__text">
        <div className="mol-connection-row__id">{id}</div>
        <div className="mol-connection-row__meta">{meta}</div>
      </div>
      <div className="mol-connection-row__spacer" />
      {status === 'configured' ? (
        <Badge variant="success">configured</Badge>
      ) : (
        <Badge variant="error">not set</Badge>
      )}
      <Button variant="secondary" size="xs" onClick={onEdit}>
        Edit
      </Button>
    </div>
  )
}

export default ConnectionRow
