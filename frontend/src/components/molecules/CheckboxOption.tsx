/**
 * CheckboxOption — a multi-select option card for elicitation questions.
 * Square checkbox instead of RadioOption's circle.
 * When `isCustom` is true and the option is selected, renders a multi-line
 * <textarea> for free-form answers (the "Other (type your own)" field).
 * Used in: elicitation decision panels (multi-select mode).
 */
import { useEffect, useRef } from 'react'
import './CheckboxOption.css'

interface CheckboxOptionProps {
  label: string
  selected?: boolean
  recommended?: boolean
  isCustom?: boolean
  customText?: string
  onCustomTextChange?: (text: string) => void
  onClick?: () => void
}

const CheckSvg = () => (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path d="M20 6L9 17l-5-5" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

export function CheckboxOption({ label, selected, recommended, isCustom, customText, onCustomTextChange, onClick }: CheckboxOptionProps) {
  const inputRef = useRef<HTMLTextAreaElement>(null)
  useEffect(() => {
    if (isCustom && selected) inputRef.current?.focus()
  }, [isCustom, selected])

  return (
    <div
      className={`co${selected ? ' co--selected' : ''}${recommended ? ' co--recommended' : ''}${isCustom ? ' co--custom' : ''}`}
      onClick={onClick}
      role="checkbox"
      aria-checked={selected}
    >
      <span className="co-box">
        {selected && <CheckSvg />}
      </span>
      <span className="co-content">
        <span className="co-label-row">
          <span className="co-label">{label}</span>
        </span>
        {isCustom && selected && (
          <textarea
            ref={inputRef}
            className="co-custom-input"
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

export default CheckboxOption
