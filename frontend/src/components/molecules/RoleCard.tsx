/**
 * RoleCard — vertical placeholder card for the first-run gate (NoProvidersBlock).
 * Dashed, dimmed, no controls. The former 'override' variant was removed: the
 * New Run per-run override now uses RoleRow's compact variant instead.
 */

import './RoleCard.css'
import { RoleMarker } from '../atoms/RoleMarker'

export type WorkflowRole = 'strong' | 'standard' | 'cheap'

const ROLE_NAME: Record<WorkflowRole, string> = {
  strong: 'Strong',
  standard: 'Standard',
  cheap: 'Cheap',
}

export interface RoleCardProps {
  role: WorkflowRole
  variant: 'not-set'
}

export function RoleCard({ role }: RoleCardProps) {
  return (
    <div className="mol-role-card mol-role-card--not-set">
      <div className="mol-role-card__marker">
        <RoleMarker role={role} size="lg" />
      </div>
      <div className="mol-role-card__name">{ROLE_NAME[role]}</div>
      <div className="mol-role-card__status">not set</div>
    </div>
  )
}

export default RoleCard
