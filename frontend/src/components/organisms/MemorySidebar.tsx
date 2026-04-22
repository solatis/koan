import { Fragment } from 'react'
import './MemorySidebar.css'
import TextInput from '../atoms/TextInput'
import MemoryFilterChips from '../molecules/MemoryFilterChips'
import MemoryCard from '../molecules/MemoryCard'

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

interface MemorySidebarProps {
  count: number
  search: string
  onSearchChange: (v: string) => void
  filter: FilterValue
  onFilterChange: (v: FilterValue) => void
  entries: SidebarEntry[]
  emptyHint?: string
}

function isDefault(search: string, filter: FilterValue) {
  return search === '' && filter === 'all'
}

export function MemorySidebar({
  count,
  search,
  onSearchChange,
  filter,
  onFilterChange,
  entries,
  emptyHint,
}: MemorySidebarProps) {
  return (
    <aside className="ms">
      <div className="ms-header">
        <span className="ms-title">Memory</span>
        <span className="ms-count">{count} entries</span>
      </div>

      <div className="ms-search">
        <TextInput
          value={search}
          onChange={onSearchChange}
          placeholder="Search memories\u2026"
        />
      </div>

      <div className="ms-filter">
        <MemoryFilterChips value={filter} onChange={onFilterChange} />
      </div>

      {entries.length === 0 ? (
        <div className="ms-empty">
          <div className="ms-empty-text">
            {isDefault(search, filter) ? 'No memories yet.' : 'No memories match.'}
          </div>
          {emptyHint && <div className="ms-empty-hint">{emptyHint}</div>}
        </div>
      ) : (
        <div className="ms-list">
          {entries.map((e, i) => (
            <Fragment key={e.seq}>
              {i > 0 && <div className="ms-divider" />}
              <div className={`ms-entry${e.outline ? ` ms-entry--${e.outline}` : ''}`}>
                <MemoryCard
                  type={e.type}
                  seq={e.seq}
                  title={e.title}
                  current={e.current}
                  onClick={e.onClick}
                />
              </div>
            </Fragment>
          ))}
        </div>
      )}
    </aside>
  )
}

export default MemorySidebar
