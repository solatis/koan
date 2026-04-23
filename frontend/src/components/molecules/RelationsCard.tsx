/**
 * RelationsCard -- shared molecule for rendering entry relations and citations.
 *
 * Promoted from MemoryDetailPage.tsx (relations) when MemoryReflectPage added
 * a second consumer (citations). Two consumers is the promotion threshold per
 * the project's design-system rule.
 *
 * Props:
 *   outgoing -- entries this record points TO
 *   incoming -- entries pointing HERE (empty list for single layout)
 *   eyebrow  -- card label, defaults to "Relations"
 *   counts   -- show outgoing/incoming counts in the head row, defaults true
 *   layout   -- 'split' shows both columns (default); 'single' shows only the
 *               outgoing column at full width (used for citations)
 */

import './RelationsCard.css'
import MemoryTypeIcon from '../atoms/MemoryTypeIcon'

type MemoryType = 'decision' | 'lesson' | 'context' | 'procedure'

export interface RelationEntry {
  seq: string
  type: MemoryType
  title: string
  age: string
  onClick?: () => void
}

interface RelationsCardProps {
  outgoing: RelationEntry[]
  incoming?: RelationEntry[]
  eyebrow?: string
  counts?: boolean
  layout?: 'split' | 'single'
}

function RelationRow({ entry }: { entry: RelationEntry }) {
  const Tag = entry.onClick ? 'button' : 'div'
  return (
    <Tag
      className="rc-row"
      type={entry.onClick ? 'button' : undefined}
      onClick={entry.onClick}
    >
      <MemoryTypeIcon type={entry.type} />
      <div className="rc-row-body">
        <div className="rc-row-head">
          <span className="rc-row-seq">{entry.seq}</span>
          <span className="rc-row-type">{entry.type}</span>
        </div>
        <span className="rc-row-title">{entry.title}</span>
      </div>
      <span className="rc-row-age">{entry.age}</span>
    </Tag>
  )
}

function RelationGroup({ arrow, label, annotation, entries, emptyText }: {
  arrow: string
  label: string
  annotation: string
  entries: RelationEntry[]
  emptyText: string
}) {
  return (
    <div>
      <div className="rc-group-title">
        <span className="rc-arrow">{arrow}</span>
        <span>{label}</span>
        <span className="rc-annot">{annotation}</span>
      </div>
      {entries.length === 0 ? (
        <div className="rc-empty">{emptyText}</div>
      ) : (
        <div className="rc-list">
          {entries.map(e => <RelationRow key={e.seq} entry={e} />)}
        </div>
      )}
    </div>
  )
}

export function RelationsCard({
  outgoing,
  incoming = [],
  eyebrow = 'Relations',
  counts = true,
  layout = 'split',
}: RelationsCardProps) {
  return (
    <div className="rc">
      <div className="rc-head">
        <span className="rc-eyebrow">{eyebrow}</span>
        {counts && layout === 'split' && (
          <span className="rc-counts">
            <span><span className="rc-count-n">{outgoing.length}</span> outgoing</span>
            <span><span className="rc-count-n">{incoming.length}</span> incoming</span>
          </span>
        )}
        {counts && layout === 'single' && (
          <span className="rc-counts">
            <span><span className="rc-count-n">{outgoing.length}</span> cited</span>
          </span>
        )}
      </div>
      {layout === 'split' ? (
        <div className="rc-split">
          <RelationGroup
            arrow={'\u2192'}
            label="References"
            annotation="this entry points to"
            entries={outgoing}
            emptyText="None"
          />
          <RelationGroup
            arrow={'\u2190'}
            label="Referenced by"
            annotation="entries pointing here"
            entries={incoming}
            emptyText="Not yet referenced by any entry"
          />
        </div>
      ) : (
        <div className="rc-single">
          {outgoing.length === 0 ? (
            <div className="rc-empty">No citations.</div>
          ) : (
            <div className="rc-list">
              {outgoing.map(e => <RelationRow key={e.seq} entry={e} />)}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default RelationsCard
