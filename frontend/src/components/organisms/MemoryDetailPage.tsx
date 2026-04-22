import './MemoryDetailPage.css'
import type { ReactNode } from 'react'
import MemoryTypeBadge from '../atoms/MemoryTypeBadge'
import MemoryTypeIcon from '../atoms/MemoryTypeIcon'
import Button from '../atoms/Button'
import MemorySidebar from './MemorySidebar'

type MemoryType = 'decision' | 'lesson' | 'context' | 'procedure'
type FilterValue = 'all' | MemoryType
type EntryOutline = 'cited' | 'retrieving' | 'outgoing' | 'incoming' | null

interface SidebarEntry {
  seq: string
  type: MemoryType
  title: string
  current?: boolean
  outline?: EntryOutline
  onClick?: () => void
}

interface EntryMeta {
  created: { date: string; age: string }
  modified: { date: string; sub: string }
  size: { value: string; sub: string }
  filename: string
  editMeta: string
}

interface EntryDetailCardProps {
  type: MemoryType
  seq: string
  title: string
  meta: EntryMeta
  children: ReactNode
  onCopyLink?: () => void
  onViewRaw?: () => void
}

interface RelationEntry {
  seq: string
  type: MemoryType
  title: string
  age: string
  onClick?: () => void
}

interface EntryRelationsCardProps {
  outgoing: RelationEntry[]
  incoming: RelationEntry[]
}

interface MemoryDetailPageProps {
  entry: {
    type: MemoryType
    seq: string
    title: string
    meta: EntryMeta
    body: ReactNode
    onCopyLink?: () => void
    onViewRaw?: () => void
  }
  relations: EntryRelationsCardProps
  sidebar: {
    count: number
    search: string
    onSearchChange: (v: string) => void
    filter: FilterValue
    onFilterChange: (v: FilterValue) => void
    entries: SidebarEntry[]
    emptyHint?: string
  }
}

function DateCell({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div>
      <div className="dc-date-label">{label}</div>
      <div className="dc-date-value">{value}</div>
      <div className="dc-date-sub">{sub}</div>
    </div>
  )
}

function EntryDetailCard({ type, seq, title, meta, children, onCopyLink, onViewRaw }: EntryDetailCardProps) {
  return (
    <div className="dc">
      <div className="dc-head">
        <MemoryTypeBadge type={type} />
        <span className="dc-seq">{seq}</span>
      </div>
      <h1 className="dc-title">{title}</h1>
      <div className="dc-dates">
        <DateCell label="Created" value={meta.created.date} sub={meta.created.age} />
        <DateCell label="Last modified" value={meta.modified.date} sub={meta.modified.sub} />
        <DateCell label="Size" value={meta.size.value} sub={meta.size.sub} />
      </div>
      <div className="dc-body">{children}</div>
      <div className="dc-filename">{meta.filename}</div>
      <div className="dc-actions">
        <span className="dc-editmeta">{meta.editMeta}</span>
        <span className="dc-spacer" />
        {onCopyLink && <Button variant="secondary" size="sm" onClick={onCopyLink}>Copy link</Button>}
        {onViewRaw && <Button variant="secondary" size="sm" onClick={onViewRaw}>View raw</Button>}
      </div>
    </div>
  )
}

function RelationRow({ entry }: { entry: RelationEntry }) {
  const Tag = entry.onClick ? 'button' : 'div'
  return (
    <Tag className="rc-row" type={entry.onClick ? 'button' : undefined} onClick={entry.onClick}>
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

function EntryRelationsCard({ outgoing, incoming }: EntryRelationsCardProps) {
  return (
    <div className="rc">
      <div className="rc-head">
        <span className="rc-eyebrow">Relations</span>
        <span className="rc-counts">
          <span><span className="rc-count-n">{outgoing.length}</span> outgoing</span>
          <span><span className="rc-count-n">{incoming.length}</span> incoming</span>
        </span>
      </div>
      <div className="rc-split">
        <RelationGroup arrow={'\u2192'} label="References" annotation="this entry points to" entries={outgoing} emptyText="None" />
        <RelationGroup arrow={'\u2190'} label="Referenced by" annotation="entries pointing here" entries={incoming} emptyText="Not yet referenced by any entry" />
      </div>
    </div>
  )
}

export function MemoryDetailPage({ entry, relations, sidebar }: MemoryDetailPageProps) {
  return (
    <div className="mdp">
      <main className="mdp-main">
        <EntryDetailCard
          type={entry.type}
          seq={entry.seq}
          title={entry.title}
          meta={entry.meta}
          onCopyLink={entry.onCopyLink}
          onViewRaw={entry.onViewRaw}
        >
          {entry.body}
        </EntryDetailCard>
        <EntryRelationsCard outgoing={relations.outgoing} incoming={relations.incoming} />
      </main>
      <MemorySidebar {...sidebar} />
    </div>
  )
}

export default MemoryDetailPage
