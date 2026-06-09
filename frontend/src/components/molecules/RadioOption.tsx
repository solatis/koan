/**
 * RadioOption — a selectable option card for elicitation questions.
 *
 * Renders a radio circle, label text, and optional "recommended" badge.
 * When `isCustom` is true and the option is selected, renders a multi-line
 * <textarea> for free-form answers (the "Other (type your own)" field).
 * Controlled component — parent manages selection state via `selected`
 * prop and `onClick` callback.
 *
 * Used in: deepen/elicitation decision panels.
 */

import { useEffect, useRef } from 'react'
import './RadioOption.css'

interface RadioOptionProps {
  label: string
  selected?: boolean
  recommended?: boolean
  isCustom?: boolean
  customText?: string
  onCustomTextChange?: (text: string) => void
  onClick?: () => void
}

export function RadioOption({ label, selected, recommended, isCustom, customText, onCustomTextChange, onClick }: RadioOptionProps) {
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (isCustom && selected) inputRef.current?.focus()
  }, [isCustom, selected])

  return (
    <div
      className={`ro${selected ? ' ro--selected' : ''}${recommended ? ' ro--recommended' : ''}${isCustom ? ' ro--custom' : ''}`}
      onClick={onClick}
      role="radio"
      aria-checked={selected}
    >
      <span className="ro-circle">
        {selected && <span className="ro-circle-inner" />}
      </span>
      <span className="ro-content">
        <span className="ro-label-row">
          <span className="ro-label">{label}</span>
        </span>
        {isCustom && selected && (
          <textarea
            ref={inputRef}
            className="ro-custom-input"
            rows={3}
            placeholder="Type your response..."
            value={customText ?? ''}
            onChange={e => onCustomTextChange?.(e.target.value)}
            onClick={e => e.stopPropagation()}
          />
        )}
      </span>
    </div>
  )
}

export default RadioOption
