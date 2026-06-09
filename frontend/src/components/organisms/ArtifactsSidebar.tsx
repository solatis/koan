/**
 * ArtifactsSidebar — right-side panel listing spec artifacts.
 *
 * Fixed 240px column beside the main content stream. Shows a section
 * label, a list of ArtifactCard molecules, or an empty-state message
 * when no artifacts exist. Cards are clickable when onArtifactClick
 * is provided; the entry whose path matches activePath is highlighted.
 *
 * Used in: workspace layout, right column.
 */

import { SectionLabel } from '../atoms/SectionLabel'
import { ArtifactCard } from '../molecules/ArtifactCard'
import './ArtifactsSidebar.css'

interface ArtifactEntry {
  path: string
  filename: string
  modifiedAgo: string
  variant?: 'recent' | 'stable'
  // True when modified after the last yield resolution; parent computes from
  // artifact.modifiedAt vs lastTouchpointMs.
  changed?: boolean
}

interface ArtifactsSidebarProps {
  artifacts: ArtifactEntry[]
  activePath?: string | null
  onArtifactClick?: (path: string) => void
}

export function ArtifactsSidebar({ artifacts, activePath, onArtifactClick }: ArtifactsSidebarProps) {
  return (
    <aside className="asb">
      <div className="asb-header">
        <SectionLabel>Artifacts</SectionLabel>
      </div>
      {artifacts.length === 0 ? (
        <div className="asb-empty">No artifacts yet</div>
      ) : (
        <div className="asb-list">
          {artifacts.map(a => (
            <ArtifactCard
              key={a.path}
              filename={a.filename}
              modifiedAgo={a.modifiedAgo}
              variant={a.variant}
              changed={a.changed}
              active={activePath === a.path}
              onClick={onArtifactClick ? () => onArtifactClick(a.path) : undefined}
            />
          ))}
        </div>
      )}
    </aside>
  )
}

export default ArtifactsSidebar
