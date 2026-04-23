import './MemoryReflectPage.css'
import type { ReactNode } from 'react'
import { useNavigate } from 'react-router'
import ProgressStrip from '../molecules/ProgressStrip'
import ThinkingBlock from '../molecules/ThinkingBlock'
import ToolCallRow from '../molecules/ToolCallRow'
import StatStrip from '../molecules/StatStrip'
import RelationsCard from '../molecules/RelationsCard'
import type { RelationEntry } from '../molecules/RelationsCard'
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

// Unified arrival-ordered trace entries for both in-progress and done states.
// Replaces the prior tools: ReflectToolCall[] field.
type ReflectTraceRender =
  | { kind: 'thinking'; delta: string }
  | { kind: 'text'; delta: string }
  | { kind: 'search'; query: string; status: 'done' | 'running'; resultCount?: number }

type InProgressProps = {
  status: 'in-progress'
  turn: number
  maxTurns: number
  elapsed: string
  model: string
  onCancel: () => void
  entries: ReflectTraceRender[]
}

type DoneProps = {
  status: 'done'
  iterations: number
  searches: number
  elapsed: string
  citedCount: number
  briefing: ReactNode
  citations: RelationEntry[]
  entries: ReflectTraceRender[]
}

type ReflectState = InProgressProps | DoneProps

interface MemoryReflectPageProps {
  question: string
  state: ReflectState
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

function BackLink() {
  const navigate = useNavigate()
  return (
    // Back-link rendered in both states so the user can abort a slow run
    // without hunting for nav. Hardcoded margin -- single-use per design-system
    // convention; value (0 0 12px) matches the eyebrow spacing below.
    <div style={{ marginBottom: 12 }}>
      <Button
        variant="text"
        size="sm"
        onClick={() => navigate('/memory')}
      >
        Back to Memory
      </Button>
    </div>
  )
}

function TraceStream({ entries }: { entries: ReflectTraceRender[] }) {
  if (entries.length === 0) return null
  return (
    <div className="rfl-trace-stream">
      {entries.map((e, i) => {
        if (e.kind === 'thinking') {
          return (
            <div key={i} style={{ marginBottom: 8 }}>
              <ThinkingBlock>{e.delta}</ThinkingBlock>
            </div>
          )
        }
        if (e.kind === 'text') {
          // Prose text deltas rendered inline; no heavy wrapper needed.
          return (
            <div key={i} className="rfl-text-delta">{e.delta}</div>
          )
        }
        // kind === 'search'
        return (
          <ToolCallRow
            key={i}
            tool="search"
            command={e.query}
            status={e.status}
            metric={e.status === 'done' ? `${e.resultCount} results` : 'retrieving\u2026'}
          />
        )
      })}
    </div>
  )
}

function ReflectPane({ question, state }: { question: string; state: ReflectState }) {
  return (
    <div className="rfl">
      <BackLink />
      <div className="rfl-eyebrow">
        {state.status === 'in-progress' ? 'Reflection \u00b7 in progress' : 'Reflection'}
      </div>
      <h1 className="rfl-question">{question}</h1>

      {state.status === 'in-progress' && (
        <>
          <ProgressStrip
            turn={state.turn}
            maxTurns={state.maxTurns}
            elapsed={state.elapsed}
            model={state.model}
            onCancel={state.onCancel}
          />
          <TraceStream entries={state.entries} />
        </>
      )}

      {state.status === 'done' && (
        <>
          <div className="rfl-done-meta">
            <StatStrip
              size="sm"
              cells={[
                { value: String(state.iterations), label: 'iterations' },
                { value: String(state.searches), label: 'searches' },
                { value: state.elapsed, label: 'elapsed' },
                { value: String(state.citedCount), label: 'cited' },
              ]}
            />
          </div>
          <TraceStream entries={state.entries} />
          <div className="rfl-briefing">{state.briefing}</div>
          {state.citations.length > 0 && (
            <div className="rfl-citations">
              <RelationsCard
                eyebrow="Citations"
                layout="single"
                outgoing={state.citations}
                incoming={[]}
              />
            </div>
          )}
        </>
      )}
    </div>
  )
}

export function MemoryReflectPage({ question, state, sidebar }: MemoryReflectPageProps) {
  return (
    <div className="mrp">
      <ReflectPane question={question} state={state} />
      <MemorySidebar {...sidebar} />
    </div>
  )
}

export default MemoryReflectPage
