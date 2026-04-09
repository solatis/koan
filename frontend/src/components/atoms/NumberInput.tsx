/**
 * NumberInput — compact numeric input for scalar configuration values.
 *
 * Used in: settings Runtime section (scout concurrency), NewRunForm
 * (scout concurrency). Auto-saves on blur — no explicit save UI.
 */

import { useState, useEffect } from 'react'
import './NumberInput.css'

interface NumberInputProps {
  value: number
  onChange: (value: number) => void
  min?: number
  max?: number
  disabled?: boolean
  className?: string
}

export function NumberInput({
  value,
  onChange,
  min,
  max,
  disabled = false,
  className,
}: NumberInputProps) {
  const [display, setDisplay] = useState(value.toString())

  useEffect(() => {
    setDisplay(value.toString())
  }, [value])

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const raw = e.target.value
    if (raw === '') {
      setDisplay('')
      return
    }
    if (!/^\d+$/.test(raw)) return
    setDisplay(raw)
  }

  const handleBlur = () => {
    let num = parseInt(display, 10)
    if (isNaN(num)) {
      setDisplay(value.toString())
      return
    }
    if (min !== undefined && num < min) num = min
    if (max !== undefined && num > max) num = max
    setDisplay(num.toString())
    onChange(num)
  }

  const cls = [
    'atom-number-input',
    className,
  ].filter(Boolean).join(' ')

  return (
    <input
      type="text"
      inputMode="numeric"
      pattern="[0-9]*"
      className={cls}
      value={display}
      onChange={handleChange}
      onBlur={handleBlur}
      disabled={disabled}
    />
  )
}

export default NumberInput
