import './MemoryReflectPage.css'
import type { ReactNode } from 'react'
import ProgressStrip from '../molecules/ProgressStrip'
import ThinkingBlock from '../molecules/ThinkingBlock'
import ToolCallRow from '../molecules/ToolCallRow'
import StatStrip from '../molecules/StatStrip'
import FeedbackInput from '../molecules/FeedbackInput'
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

type ReflectToolCall = {
  query: string
  status: 'done' | 'running'
  resultCount?: number
}

type InProgressProps = {
  status: 'in-progress'
  turn: number
  maxTurns: number
  elapsed: string
  model: string
  onCancel: () => void
  thinking?: string
  tools: ReflectToolCall[]
}

type DoneProps = {
  status: 'done'
  iterations: number
  searches: number
  elapsed: string
  citedCount: number
  briefing: ReactNode
  onFollowUpSend: (v: string) => void
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

function ReflectPane({ question, state }: { question: string; state: ReflectState }) {
  return (
    <div className="rfl">
      <div className="rfl-eyebrow">
        {state.status === 'in-progress' ? 'Reflection \u00b7 in progress' : 'Briefing'}
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
          {state.thinking && (
            <div style={{ marginTop: 14 }}>
              <ThinkingBlock>{state.thinking}</ThinkingBlock>
            </div>
          )}
          {state.tools.length > 0 && (
            <div className="rfl-tools">
              {state.tools.map((t, i) => (
                <ToolCallRow
                  key={i}
                  tool="search"
                  command={t.query}
                  status={t.status}
                  metric={t.status === 'done' ? `${t.resultCount} results` : 'retrieving\u2026'}
                />
              ))}
            </div>
          )}
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
          <div className="rfl-briefing">{state.briefing}</div>
          <div className="rfl-followup">
            <div className="rfl-followup-label">Follow up</div>
            <FeedbackInput
              placeholder="Ask a follow-up question about this briefing, or explore a related angle\u2026"
              onSend={state.onFollowUpSend}
            />
          </div>
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
