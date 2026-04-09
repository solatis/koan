/**
 * Select — shared dropdown select for all forms.
 *
 * Used in: settings profile forms (runner, model, thinking cascade),
 * settings installation forms (runner type), NewRunForm (profile select,
 * installation select), and standalone preference selects.
 */

import './Select.css'

interface SelectOption {
  value: string
  label: string
}

interface SelectProps {
  value: string
  onChange: (value: string) => void
  options: SelectOption[]
  placeholder?: string
  disabled?: boolean
  mono?: boolean
  className?: string
}

export function Select({
  value,
  onChange,
  options,
  placeholder,
  disabled = false,
  mono = false,
  className,
}: SelectProps) {
  const cls = [
    'atom-select',
    value === '' && placeholder && 'atom-select--placeholder',
    mono && 'atom-select--mono',
    className,
  ].filter(Boolean).join(' ')

  return (
    <select
      className={cls}
      value={value}
      onChange={e => onChange(e.target.value)}
      disabled={disabled}
    >
      {placeholder && (
        <option value="" disabled hidden>{placeholder}</option>
      )}
      {options.map(opt => (
        <option key={opt.value} value={opt.value}>{opt.label}</option>
      ))}
    </select>
  )
}

export default Select
