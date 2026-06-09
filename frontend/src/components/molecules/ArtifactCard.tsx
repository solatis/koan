/**
 * ArtifactCard — a file entry in the artifacts sidebar.
 *
 * Shows a colored icon square, filename (truncated), and a
 * last-modified timestamp. "recent" files get a navy icon,
 * "stable" files get a teal icon. Clickable when onClick is
 * provided; highlights when `active`.
 *
 * Used in: artifacts sidebar.
 */

import './ArtifactCard.css'

interface ArtifactCardProps {
  filename: string
  modifiedAgo: string
  variant?: 'recent' | 'stable'
  active?: boolean
  onClick?: () => void
  // True when the artifact was modified after the last yield resolution;
  // drives the amber dot indicator in the sidebar.
  changed?: boolean
}

const FileIcon = ({ stroke }: { stroke: string }) => (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" stroke={stroke} strokeWidth="2" />
    <path d="M14 2v6h6" stroke={stroke} strokeWidth="2" />
  </svg>
)

export function ArtifactCard({ filename, modifiedAgo, variant = 'recent', active, onClick, changed }: ArtifactCardProps) {
  const cls = `ac${onClick ? ' ac--clickable' : ''}${active ? ' ac--active' : ''}`
  return (
    <div className={cls} onClick={onClick} role={onClick ? 'button' : undefined} tabIndex={onClick ? 0 : undefined}>
      <span className={`ac-icon ac-icon--${variant}`}>
        <FileIcon stroke={variant === 'recent' ? '#b8b0d0' : '#d0f0e8'} />
      </span>
      <span className="ac-info">
        <span className="ac-filename">
          {filename}
          {changed && <span className="ac-changed" aria-label="changed since last touchpoint" />}
        </span>
        <span className="ac-time">{modifiedAgo}</span>
      </span>
    </div>
  )
}

export default ArtifactCard
