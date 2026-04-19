/**
 * Toggle — boolean switch for auto-saving preferences.
 *
 * Used in: settings SettingRow (auto-open artifacts, sandbox execution,
 * verbose debug output, and future boolean preferences).
 *
 * Auto-saves on click. The parent component handles the API call —
 * no explicit save UI.
 */

import './Toggle.css'

interface ToggleProps {
  checked: boolean
  onChange: (checked: boolean) => void
  disabled?: boolean
}

export function Toggle({ checked, onChange, disabled = false }: ToggleProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      className={`atom-toggle atom-toggle--${checked ? 'on' : 'off'}`}
      onClick={() => !disabled && onChange(!checked)}
      disabled={disabled}
    >
      <span className="atom-toggle__thumb" />
    </button>
  )
}

export default Toggle
