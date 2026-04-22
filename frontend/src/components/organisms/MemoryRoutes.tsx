/**
 * MemoryRoutes -- URL-driven switcher for the four memory sub-pages.
 *
 * Mounted by App.tsx when page === 'memory'. Contains Connected* wrappers
 * that fetch data from the backend and bridge it to the page organism props.
 * Page organisms themselves are not modified.
 */

import { useState, useEffect, useMemo } from 'react'
import { Routes, Route, Navigate, useParams, useNavigate } from 'react-router'
import type { ReactNode } from 'react'

import { useStore } from '../../store/index'
import type { MemoryEntrySummary } from '../../store/index'
import * as api from '../../api/client'
import { Md } from '../Md'
import { useMemorySearch } from '../../hooks/useMemorySearch'
import { Button } from '../atoms/Button'

import { MemoryOverviewPage } from './MemoryOverviewPage'
import { MemoryDetailPage } from './MemoryDetailPage'
import { MemoryReflectPage } from './MemoryReflectPage'
import MemorySidebar from './MemorySidebar'

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

function renderAge(ms: number): string {
  const diff = Math.floor((Date.now() - ms) / 1000)
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  if (diff < 172800) return 'yesterday'
  return `${Math.floor(diff / 86400)}d ago`
}

function formatDate(ms: number): string {
  if (!ms) return '--'
  return new Date(ms).toLocaleDateString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
  })
}

function buildSidebarEntries(
  entries: Record<string, MemoryEntrySummary>,
  filter: 'all' | string,
  currentSeq?: string,
  onClickEntry?: (seq: string) => void,
) {
  // Caller is responsible for passing either the full store entries (empty
  // search) or the backend-ranked results converted to a record (non-empty
  // search). Title filtering is no longer done here -- backend reranking
  // is the authority when a query is present.
  return Object.values(entries)
    .filter(e => filter === 'all' || e.type === filter)
    .sort((a, b) => b.modifiedMs - a.modifiedMs)
    .map(e => ({
      seq: e.seq,
      type: e.type,
      title: e.title,
      current: e.seq === currentSeq,
      onClick: onClickEntry ? () => onClickEntry(e.seq) : undefined,
    }))
}

// ---------------------------------------------------------------------------
// ReflectPaneEmpty -- rendered when /memory/reflect is visited with no
// active reflect session. Avoids the redirect race by staying in place;
// the store update from SSE will swap this for the real page on next render.
// ---------------------------------------------------------------------------

function ReflectPaneEmpty() {
  const navigate = useNavigate()
  return (
    <div className="rfl">
      <div className="rfl-eyebrow">Reflection</div>
      <p style={{ color: 'var(--text-subtle)', margin: '0 0 16px' }}>
        No active reflection. Ask a question on the Memory overview.
      </p>
      <Button variant="text" size="sm" onClick={() => navigate('/memory')}>
        Back to Memory
      </Button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// ConnectedMemoryOverview
// ---------------------------------------------------------------------------

function ConnectedMemoryOverview() {
  const navigate = useNavigate()
  const entries = useStore(s => s.memory.entries)
  const storeSummary = useStore(s => s.memory.summary)
  const sidebar = useStore(s => s.memorySidebar)
  const setSidebarSearch = useStore(s => s.setMemorySidebarSearch)
  const setSidebarFilter = useStore(s => s.setMemorySidebarFilter)
  const upsertMemoryEntries = useStore(s => s.upsertMemoryEntries)
  const [reflectQuestion, setReflectQuestion] = useState('')
  const [summary, setSummary] = useState(storeSummary)

  // Fetch entries and summary on mount. Merge into store rather than replace
  // so server-patched state (from SSE events) takes precedence after initial load.
  useEffect(() => {
    api.listMemoryEntries().then(r => {
      upsertMemoryEntries(r.entries as MemoryEntrySummary[])
    }).catch(() => {})
    api.getMemorySummary().then(r => {
      setSummary(r.summary)
    }).catch(() => {})
  }, [])

  // Keep summary in sync with store updates from SSE patches.
  useEffect(() => { setSummary(storeSummary) }, [storeSummary])

  const counts = useMemo(() => {
    const vals = Object.values(entries)
    return {
      entries: vals.length,
      decisions: vals.filter(e => e.type === 'decision').length,
      lessons: vals.filter(e => e.type === 'lesson').length,
      context: vals.filter(e => e.type === 'context').length,
      procedures: vals.filter(e => e.type === 'procedure').length,
    }
  }, [entries])

  // Activity: most-recently modified entries as simple event rows.
  const activity = useMemo(() => {
    return Object.values(entries)
      .sort((a, b) => b.modifiedMs - a.modifiedMs)
      .slice(0, 10)
      .map(e => ({
        time: renderAge(e.modifiedMs),
        body: <Md>{`Entry #${e.seq} -- **${e.title}**`}</Md> as ReactNode,
      }))
  }, [entries])

  const { results } = useMemorySearch(sidebar.search, sidebar.filter)

  // When search is non-empty, use the backend-ranked results; otherwise fall
  // back to the full store entry set with client-side type filter.
  const effectiveEntries = useMemo<Record<string, MemoryEntrySummary>>(() => {
    if (results === null) return entries
    return Object.fromEntries(results.map(e => [e.seq, e]))
  }, [results, entries])

  const sidebarEntries = useMemo(() =>
    buildSidebarEntries(
      effectiveEntries,
      results !== null ? 'all' : sidebar.filter,
      undefined,
      seq => navigate(`/memory/${seq}`),
    ),
    [effectiveEntries, results, sidebar.filter])

  const handleAsk = async (q: string) => {
    if (!q.trim()) return
    await api.startReflect(q).catch(() => {})
    navigate('/memory/reflect')
  }

  return (
    <MemoryOverviewPage
      counts={counts}
      summary={<Md>{summary || '_No summary yet._'}</Md>}
      reflect={{
        value: reflectQuestion,
        onChange: setReflectQuestion,
        onAsk: handleAsk,
      }}
      activity={activity}
      sidebar={{
        count: Object.keys(entries).length,
        search: sidebar.search,
        onSearchChange: setSidebarSearch,
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        filter: sidebar.filter as any,
        // The store's MemoryType and the page organism's local MemoryType are
        // structurally identical but declared separately, causing a type error.
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        onFilterChange: setSidebarFilter as (v: any) => void,
        entries: sidebarEntries,
        emptyHint: 'No entries match your filter.',
      }}
    />
  )
}

// ---------------------------------------------------------------------------
// ConnectedMemoryDetail
// ---------------------------------------------------------------------------

function ConnectedMemoryDetail() {
  const navigate = useNavigate()
  const { seq } = useParams<{ seq: string }>()
  const entries = useStore(s => s.memory.entries)
  const sidebar = useStore(s => s.memorySidebar)
  const setSidebarSearch = useStore(s => s.setMemorySidebarSearch)
  const setSidebarFilter = useStore(s => s.setMemorySidebarFilter)
  const upsertMemoryEntries = useStore(s => s.upsertMemoryEntries)
  const [detail, setDetail] = useState<api.MemoryEntryDetailWire | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!seq) return
    setDetail(null)
    setError(null)
    api.getMemoryEntry(seq).then(d => {
      setDetail(d)
      // Upsert the summary into the store so sidebar stays consistent.
      upsertMemoryEntries([{
        seq: d.entry.seq,
        type: d.entry.type,
        title: d.entry.title,
        createdMs: d.entry.createdMs,
        modifiedMs: d.entry.modifiedMs,
      }])
    }).catch(e => setError(String(e)))
  }, [seq])

  const { results } = useMemorySearch(sidebar.search, sidebar.filter)

  const effectiveEntries = useMemo<Record<string, MemoryEntrySummary>>(() => {
    if (results === null) return entries
    return Object.fromEntries(results.map(e => [e.seq, e]))
  }, [results, entries])

  const sidebarEntries = useMemo(() => {
    // Mark outgoing and incoming relations distinctly in the sidebar.
    const outSeqs = new Set(detail?.relations.outgoing.map(r => r.seq) ?? [])
    const inSeqs = new Set(detail?.relations.incoming.map(r => r.seq) ?? [])
    return buildSidebarEntries(
      effectiveEntries,
      results !== null ? 'all' : sidebar.filter,
      seq,
      seq2 => navigate(`/memory/${seq2}`),
    ).map(e => ({
      ...e,
      outline: outSeqs.has(e.seq) ? 'outgoing' as const
        : inSeqs.has(e.seq) ? 'incoming' as const
        : undefined,
    }))
  }, [effectiveEntries, results, sidebar.filter, seq, detail])

  if (error) {
    return <div style={{ padding: 32 }}>Error loading entry: {error}</div>
  }

  if (!detail) {
    return <div style={{ padding: 32 }}>Loading...</div>
  }

  const e = detail.entry
  const meta = {
    created: {
      date: formatDate(e.createdMs),
      age: renderAge(e.createdMs),
    },
    modified: {
      date: formatDate(e.modifiedMs),
      sub: renderAge(e.modifiedMs),
    },
    size: {
      value: `${e.body.length} chars`,
      sub: `~${Math.ceil(e.body.split(/\s+/).length / 150)} min read`,
    },
    filename: e.filename,
    editMeta: `Edit .koan/memory/${e.filename}`,
  }

  const outgoing = detail.relations.outgoing.map(r => ({
    seq: r.seq,
    type: r.type,
    title: r.title,
    age: r.age,
    onClick: () => navigate(`/memory/${r.seq}`),
  }))

  const incoming = detail.relations.incoming.map(r => ({
    seq: r.seq,
    type: r.type,
    title: r.title,
    age: r.age,
    onClick: () => navigate(`/memory/${r.seq}`),
  }))

  return (
    <MemoryDetailPage
      entry={{
        type: e.type,
        seq: e.seq,
        title: e.title,
        meta,
        body: <Md>{e.body}</Md>,
      }}
      relations={{ outgoing, incoming }}
      sidebar={{
        count: Object.keys(entries).length,
        search: sidebar.search,
        onSearchChange: setSidebarSearch,
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        filter: sidebar.filter as any,
        // The store's MemoryType and the page organism's local MemoryType are
        // structurally identical but declared separately, causing a type error.
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        onFilterChange: setSidebarFilter as (v: any) => void,
        entries: sidebarEntries,
      }}
    />
  )
}

// ---------------------------------------------------------------------------
// ConnectedMemoryReflect
// ---------------------------------------------------------------------------

function ConnectedMemoryReflect() {
  const reflect = useStore(s => s.reflect)
  const entries = useStore(s => s.memory.entries)
  const sidebar = useStore(s => s.memorySidebar)
  const setSidebarSearch = useStore(s => s.setMemorySidebarSearch)
  const setSidebarFilter = useStore(s => s.setMemorySidebarFilter)
  const navigate = useNavigate()

  // All hooks must be called before any early return (Rules of Hooks).
  const { results } = useMemorySearch(sidebar.search, sidebar.filter)

  const effectiveEntries = useMemo<Record<string, MemoryEntrySummary>>(() => {
    if (results === null) return entries
    return Object.fromEntries(results.map(e => [e.seq, e]))
  }, [results, entries])

  const sidebarEntries = useMemo(() =>
    buildSidebarEntries(
      effectiveEntries,
      results !== null ? 'all' : sidebar.filter,
      undefined,
      seq => navigate(`/memory/${seq}`),
    ),
    [effectiveEntries, results, sidebar.filter])

  // Render an inline empty state instead of redirecting so that direct-URL
  // entry to /memory/reflect is handled gracefully without a URL bounce.
  // The SSE -> store update will swap this for the real page on next render.
  if (!reflect) {
    return (
      <div className="mrp">
        <ReflectPaneEmpty />
        <MemorySidebar
          count={Object.keys(entries).length}
          search={sidebar.search}
          onSearchChange={setSidebarSearch}
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          filter={sidebar.filter as any}
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          onFilterChange={setSidebarFilter as (v: any) => void}
          entries={sidebarEntries}
        />
      </div>
    )
  }

  // Tools list: one entry per search trace.
  const tools = reflect.traces
    .filter(t => t.tool === 'search')
    .map(t => ({
      query: t.query,
      status: 'done' as const,
      resultCount: t.resultCount ?? undefined,
    }))

  const isDone = reflect.status === 'done' || reflect.status === 'cancelled' || reflect.status === 'failed'
  const elapsedMs = isDone && reflect.completedAtMs
    ? reflect.completedAtMs - reflect.startedAtMs
    : Date.now() - reflect.startedAtMs
  const elapsedSec = Math.floor(elapsedMs / 1000)
  const elapsed = elapsedSec < 60
    ? `${elapsedSec}s`
    : `${Math.floor(elapsedSec / 60)}m ${elapsedSec % 60}s`

  const state = isDone
    ? {
        status: 'done' as const,
        iterations: reflect.iteration,
        searches: tools.length,
        elapsed,
        citedCount: reflect.citations.length,
        briefing: <Md>{reflect.answer || reflect.error || '(no answer)'}</Md> as ReactNode,
        onFollowUpSend: async (q: string) => {
          await api.startReflect(q).catch(() => {})
        },
      }
    : {
        status: 'in-progress' as const,
        turn: reflect.iteration,
        maxTurns: reflect.maxIterations,
        elapsed,
        model: reflect.model || 'gemini',
        onCancel: () => api.cancelReflect().catch(() => {}),
        thinking: '',
        tools,
      }

  return (
    <MemoryReflectPage
      question={reflect.question}
      state={state}
      sidebar={{
        count: Object.keys(entries).length,
        search: sidebar.search,
        onSearchChange: setSidebarSearch,
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        filter: sidebar.filter as any,
        // The store's MemoryType and the page organism's local MemoryType are
        // structurally identical but declared separately, causing a type error.
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        onFilterChange: setSidebarFilter as (v: any) => void,
        entries: sidebarEntries,
      }}
    />
  )
}

// ---------------------------------------------------------------------------
// MemoryRoutes -- exported entry point
// ---------------------------------------------------------------------------

export function MemoryRoutes() {
  // Use absolute paths because this Routes is not nested inside a parent Route.
  // React Router v7 matches absolute paths from the start of the URL.
  return (
    <Routes>
      <Route path="/memory" element={<ConnectedMemoryOverview />} />
      <Route path="/memory/reflect" element={<ConnectedMemoryReflect />} />
      <Route path="/memory/:seq" element={<ConnectedMemoryDetail />} />
      <Route path="*" element={<Navigate to="/memory" replace />} />
    </Routes>
  )
}
