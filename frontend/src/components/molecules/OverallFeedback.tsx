import { useEffect } from 'react'
import { useFileAttachment } from '../../hooks/useFileAttachment'
import TextInput from '../atoms/TextInput'
import { FileChip } from '../atoms/FileChip'
import './OverallFeedback.css'

interface OverallFeedbackProps {
  value: string
  onChange: (value: string) => void
  // Notifies the parent of the current committed file ID list; uncontrolled
  // internally so parents don't need to mirror uploading/error states.
  onFileIdsChange?: (ids: string[]) => void
  label?: string
  placeholder?: string
  disabled?: boolean
}

const PaperclipIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.49" />
  </svg>
)

export function OverallFeedback({
  value,
  onChange,
  onFileIdsChange,
  label = 'Overall feedback (optional)',
  placeholder = 'Summarize your overall feedback on this document, or leave empty to submit only inline comments.',
  disabled,
}: OverallFeedbackProps) {
  const attach = useFileAttachment()

  // Fire the callback whenever the committed file list changes so the parent
  // can include IDs in its submit payload without owning upload state itself.
  // onFileIdsChange is intentionally excluded from deps: re-notifying with the
  // same fileIds when only the callback identity flipped is semantic noise and
  // (with an inline arrow at the parent) drives an infinite render loop.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    onFileIdsChange?.(attach.fileIds)
  }, [attach.fileIds])

  return (
    <div className="of" {...attach.dragProps}>
      <span className="of-label">{label}</span>
      <div className="of-textarea-wrap">
        <TextInput
          as="textarea"
          value={value}
          onChange={onChange}
          placeholder={placeholder}
          disabled={disabled}
          className="of-textarea"
        />
        <button
          className="of-attach-btn"
          onClick={attach.openPicker}
          title="Attach files"
          type="button"
          disabled={disabled}
        >
          <PaperclipIcon />
        </button>
        <input
          ref={attach.inputRef}
          type="file"
          multiple
          className="of-file-input"
          onChange={attach.onInputChange}
          tabIndex={-1}
        />
      </div>
      {attach.files.length > 0 && (
        <div className="of-chips">
          {attach.files.map(f => (
            <FileChip
              key={f.id}
              name={f.name}
              size={f.size}
              state={f.state}
              onRemove={() => attach.removeFile(f.id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

export default OverallFeedback
