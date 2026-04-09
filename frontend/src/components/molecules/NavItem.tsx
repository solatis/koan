/**
 * NavItem — side navigation item for the Settings page left nav.
 *
 * Used in: SettingsPage organism left navigation (Profiles, Agents,
 * Runtime section switcher).
 */

import './NavItem.css'

interface NavItemProps {
  label: string
  active?: boolean
  onClick?: () => void
}

export function NavItem({ label, active = false, onClick }: NavItemProps) {
  return (
    <button
      type="button"
      className={`nav-item${active ? ' nav-item--active' : ''}`}
      onClick={onClick}
    >
      {label}
    </button>
  )
}

export default NavItem
