/**
 * RoleMarker — a colored rounded square identifying a model role.
 *
 * Sibling of MemoryTypeIcon, but with NO letter: role identity is carried by
 * color plus an adjacent text label (a letter would collide — Strong and
 * Standard both start with "S"). Static, no content, no hover.
 *
 * Used in: RoleRow (Settings model-roles + memory rows) and RoleCard
 * (New Run override + first-run gate).
 */

import './RoleMarker.css'

type Role = 'strong' | 'standard' | 'cheap' | 'memory'
type Size = 'sm' | 'lg'

interface RoleMarkerProps {
  role: Role
  size?: Size
}

export function RoleMarker({ role, size = 'sm' }: RoleMarkerProps) {
  return (
    <span
      className={`atom-role-marker atom-role-marker--${role} atom-role-marker--${size}`}
      aria-hidden="true"
    />
  )
}

export default RoleMarker
