import './MemoryFilterChips.css'

type FilterValue = 'all' | 'decision' | 'lesson' | 'context' | 'procedure'

const CHIPS: FilterValue[] = ['all', 'decision', 'lesson', 'context', 'procedure']

interface MemoryFilterChipsProps {
  value: FilterValue
  onChange: (v: FilterValue) => void
}

export function MemoryFilterChips({ value, onChange }: MemoryFilterChipsProps) {
  return (
    <div className="mfc" role="group" aria-label="Filter by memory type">
      {CHIPS.map(c => (
        <button
          key={c}
          type="button"
          className={`mfc-chip${c === value ? ' mfc-chip--active' : ''}`}
          aria-pressed={c === value}
          onClick={() => onChange(c)}
        >
          {c}
        </button>
      ))}
    </div>
  )
}

export default MemoryFilterChips
