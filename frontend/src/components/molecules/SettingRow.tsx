/**
 * SettingRow — horizontal layout for individual auto-saving preference
 * controls: label + description on the left, compact control on the right.
 *
 * Used in: settings Runtime section (toggles, selects, number inputs),
 * settings Preferences section, and future preference panels.
 *
 * The right-side control is passed as children — typically a Toggle,
 * Select, or NumberInput atom.
 */

import type { ReactNode } from 'react'
import './SettingRow.css'

interface SettingRowProps {
  label: string
  description?: string
  children: ReactNode
}

export function SettingRow({ label, description, children }: SettingRowProps) {
  return (
    <div className="setting-row">
      <div className="setting-row-text">
        <div className="setting-row-label">{label}</div>
        {description && (
          <div className="setting-row-desc">{description}</div>
        )}
      </div>
      <div className="setting-row-control">
        {children}
      </div>
    </div>
  )
}

export default SettingRow
