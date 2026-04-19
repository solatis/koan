/**
 * TextInput — shared text input for all forms.
 *
 * Used in: settings forms (profile name, binary path, extra args),
 * NewRunForm (description textarea, concurrency input),
 * RadioOption/CheckboxOption (custom "Other" text input),
 * FeedbackInput (message textarea).
 *
 * Two variants: "field" (bordered rectangle) and "inline" (bottom-border
 * only, for embedded contexts like RadioOption custom input).
 */

import './TextInput.css'

interface TextInputProps {
  value: string
  onChange: (value: string) => void
  placeholder?: string
  variant?: 'field' | 'inline'
  mono?: boolean
  error?: boolean
  disabled?: boolean
  as?: 'input' | 'textarea'
  className?: string
}

export function TextInput({
  value,
  onChange,
  placeholder,
  variant = 'field',
  mono = false,
  error = false,
  disabled = false,
  as = 'input',
  className,
}: TextInputProps) {
  const Tag = as
  const cls = [
    'atom-text-input',
    `atom-text-input--${variant}`,
    mono && 'atom-text-input--mono',
    error && 'atom-text-input--error',
    className,
  ].filter(Boolean).join(' ')

  return (
    <Tag
      className={cls}
      value={value}
      onChange={(e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange(e.target.value)}
      placeholder={placeholder}
      disabled={disabled}
      {...(as === 'textarea' ? { rows: 3 } : {})}
    />
  )
}

export default TextInput
