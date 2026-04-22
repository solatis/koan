import './OverallFeedback.css'
import TextInput from '../atoms/TextInput'

interface OverallFeedbackProps {
  value: string
  onChange: (value: string) => void
  label?: string
  placeholder?: string
  disabled?: boolean
}

export function OverallFeedback({
  value,
  onChange,
  label = 'Overall feedback (optional)',
  placeholder = 'Summarize your overall feedback on this document, or leave empty to submit only inline comments.',
  disabled,
}: OverallFeedbackProps) {
  return (
    <div className="of">
      <span className="of-label">{label}</span>
      <TextInput
        as="textarea"
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        disabled={disabled}
      />
    </div>
  )
}

export default OverallFeedback
