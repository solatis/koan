import './FileChip.css'

type FileChipState = 'ready' | 'uploading' | 'error'

interface FileChipProps {
  name: string
  size: string
  state?: FileChipState
  onRemove?: () => void
}

const XIcon = () => (
  <svg width="8" height="8" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
    <path d="M2 2l8 8M10 2l-8 8" />
  </svg>
)

export function FileChip({ name, size, state = 'ready', onRemove }: FileChipProps) {
  return (
    <span className={`atom-file-chip atom-file-chip--${state}`}>
      <span className="atom-file-chip-name">
        {state === 'uploading' ? 'Uploading...' : name}
      </span>
      {state === 'ready' && (
        <span className="atom-file-chip-size">{size}</span>
      )}
      {state !== 'uploading' && onRemove && (
        <button
          className="atom-file-chip-dismiss"
          onClick={onRemove}
          aria-label={`Remove ${name}`}
          type="button"
        >
          <XIcon />
        </button>
      )}
    </span>
  )
}

export default FileChip
