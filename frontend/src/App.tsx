/*
 * EVENT TYPE → MOLECULE MAPPING (final, no gaps)
 * ─────────────────────────────────────────────────
 * thinking             → ThinkingBlock + Md
 * text                 → ProseCard + Md
 * tool_read/write/edit → ToolCallRow
 * tool_bash/grep/ls    → ToolCallRow
 * tool_generic         → ToolCallRow (koan_* orchestration tools suppressed)
 * step                 → StepHeader
 * debug_step_guidance  → StepGuidancePill + Md
 * user_message         → UserBubble + Md
 * phase_boundary       → PhaseMarker
 * yield                → YieldPanel
 * pendingThinking      → ThinkingBlock (always expanded)
 * pendingText          → ProseCard + Md + streaming cursor
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { useStore, ConversationEntry, AskQuestion } from './store/index'
// DEBUG: expose store to window for browser-agent introspection
;(window as unknown as { __store: typeof useStore }).__store = useStore
import { connectSSE } from './sse/connect'
import { useElapsed, formatElapsed } from './hooks/useElapsed'
import { useAutoScroll } from './hooks/useAutoScroll'
import { normalizeOptions } from './utils'
import * as api from './api/client'

import { HeaderBar } from './components/organisms/HeaderBar'
import { ArtifactsSidebar as ArtifactsSidebarOrg } from './components/organisms/ArtifactsSidebar'
import { ScoutBar } from './components/organisms/ScoutBar'
import { ElicitationPanel } from './components/organisms/ElicitationPanel'
import { NewRunForm } from './components/organisms/NewRunForm'

import { ThinkingBlock } from './components/molecules/ThinkingBlock'
import { ProseCard } from './components/molecules/ProseCard'
import { ToolCallRow } from './components/molecules/ToolCallRow'
import { ToolLogRow } from './components/molecules/ToolLogRow'
import { ToolStatBlock } from './components/molecules/ToolStatBlock'
import { ToolAggregateCard } from './components/molecules/ToolAggregateCard'
import { StepGuidancePill } from './components/molecules/StepGuidancePill'
import { FeedbackInput } from './components/molecules/FeedbackInput'
import { UserBubble } from './components/molecules/UserBubble'
import { PhaseMarker } from './components/molecules/PhaseMarker'
import { YieldPanel } from './components/molecules/YieldPanel'
import { StepHeader } from './components/molecules/StepHeader'
import { CompletionBanner } from './components/molecules/CompletionBanner'
import { SteeringBar } from './components/molecules/SteeringBar'

import { Md } from './components/Md'
import { Notification } from './components/Notification'
// SettingsOverlay is no longer rendered — replaced by SettingsPage organism
// import { SettingsOverlay } from './components/SettingsOverlay'
import { SettingsPage, type Profile as SPProfile, type Installation as SPInstallation } from './components/organisms/SettingsPage'
import { ReviewPanel, type ReviewSubmitPayload } from './components/organisms/ReviewPanel'
import { SessionsPage } from './components/organisms/SessionsPage'

import type { AggregateChild, AggregateReadChild, AggregateGrepChild, AggregateLsChild, ToolAggregateEntry } from './store/index'

// ---------------------------------------------------------------------------
// Header data
// ---------------------------------------------------------------------------

function useHeaderData() {
  const run = useStore(s => s.run)
  const agents = useStore(s => s.run?.agents)
  const primary = useMemo(() => agents ? Object.values(agents).find(a => a.isPrimary) : null, [agents])
  const lastStep = useMemo(() => {
    if (!primary) return null
    for (let i = primary.conversation.entries.length - 1; i >= 0; i--) {
      const e = primary.conversation.entries[i]
      if (e.type === 'step') return e
    }
    return null
  }, [primary])
  const elapsed = useElapsed(primary?.startedAtMs ?? Date.now())
  return {
    phase: run?.phase ? run.phase.split('-').map(w => w[0].toUpperCase() + w.slice(1)).join(' ') : '',
    step: lastStep?.stepName ?? primary?.stepName ?? '',
    totalSteps: lastStep?.totalSteps ?? 0,
    currentStep: lastStep?.step ?? 0,
    orchestratorModel: primary?.model ?? undefined,
    elapsed: primary ? elapsed : undefined,
  }
}

// ---------------------------------------------------------------------------
// Sidebar + scout bar wiring
// ---------------------------------------------------------------------------

function ConnectedSidebar() {
  const artifacts = useStore(s => s.run?.artifacts ?? {})
  const reviewingArtifact = useStore(s => s.reviewingArtifact)
  const setReviewingArtifact = useStore(s => s.setReviewingArtifact)
  const entries = useMemo(() => {
    const now = Date.now()
    const list = Object.values(artifacts).map(a => {
      const mins = Math.floor((now - a.modifiedAt) / 60000)
      return {
        path: a.path,
        filename: a.path.split('/').pop() || a.path,
        modifiedAgo: mins < 1 ? 'just now' : mins < 60 ? `modified ${mins}m ago` : `modified ${Math.floor(mins / 60)}h ago`,
        variant: mins < 5 ? ('recent' as const) : ('stable' as const),
        _ts: a.modifiedAt,
      }
    })
    list.sort((a, b) => b._ts - a._ts)
    return list.map(({ path, filename, modifiedAgo, variant }) => ({ path, filename, modifiedAgo, variant }))
  }, [artifacts])
  const handleClick = (path: string) => {
    setReviewingArtifact(reviewingArtifact === path ? null : path)
  }
  return <ArtifactsSidebarOrg artifacts={entries} activePath={reviewingArtifact} onArtifactClick={handleClick} />
}

function ConnectedScoutBar() {
  const agents = useStore(s => s.run?.agents ?? {})
  const scouts = useMemo(() => {
    const now = Date.now()
    return Object.values(agents).filter(a => !a.isPrimary).map(a => ({
      name: a.label || a.role,
      model: a.model ?? '--',
      status: a.status,
      tools: a.conversation.entries.filter(e => e.type.startsWith('tool_')).length,
      elapsed: a.completedAtMs
        ? formatElapsed(a.completedAtMs - (a.startedAtMs || 0))
        : formatElapsed(a.startedAtMs ? now - a.startedAtMs : 0),
      currentStep: a.status === 'done' ? 'Done'
        : a.status === 'failed' ? (a.error || 'failed')
        : a.lastTool || a.stepName || (a.step > 0 ? `step ${a.step}` : 'step 0'),
    }))
  }, [agents])
  return <ScoutBar scouts={scouts} />
}

// ---------------------------------------------------------------------------
// Content stream
// ---------------------------------------------------------------------------

// Orchestration tools whose effects are visible through other molecules
// (StepHeader, PhaseMarker). They should not render as rows.
const SUPPRESSED_TOOLS = new Set(['koan_complete_step', 'koan_set_phase'])

const KOAN_TOOL_LABELS: Record<string, string> = {
  koan_request_scouts: 'Dispatching scouts',
  koan_ask_question: 'Asking question',
  koan_yield: 'Preparing response',
  koan_request_executor: 'Starting executor',
  koan_select_story: 'Selecting story',
  koan_complete_story: 'Completing story',
  koan_retry_story: 'Retrying story',
  koan_skip_story: 'Skipping story',
}

// ---------------------------------------------------------------------------
// Aggregate rendering helpers — pure functions, next to renderEntry so the
// data flow stays readable. Each maps AggregateChild state to display strings
// or further structured pieces consumed by the card / row components.
// ---------------------------------------------------------------------------

function pluralizeOps(n: number): string {
  return n === 1 ? '1 op' : `${n} ops`
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  const kb = n / 1024
  if (kb < 1024) return `${kb.toFixed(1)} KB`
  return `${(kb / 1024).toFixed(1)} MB`
}

function childCommand(child: AggregateChild): string {
  switch (child.tool) {
    case 'read': return child.lines ? `${child.file}:${child.lines}` : child.file
    case 'grep': return child.pattern
    case 'ls':   return child.path
  }
}

function childMetric(child: AggregateChild): string | undefined {
  switch (child.tool) {
    case 'read': {
      if (child.linesRead != null && child.bytesRead != null) {
        return `${child.linesRead} lines · ${formatBytes(child.bytesRead)}`
      }
      if (child.linesRead != null) return `${child.linesRead} lines`
      return undefined
    }
    case 'grep': {
      if (child.matches != null && child.filesMatched != null) {
        return `${child.matches} matches · ${child.filesMatched} files`
      }
      if (child.matches != null) return `${child.matches} matches`
      return undefined
    }
    case 'ls': {
      if (child.entries != null) return `${child.entries} entries`
      return undefined
    }
  }
}

function shortBasename(path: string): string {
  const slash = path.lastIndexOf('/')
  return slash >= 0 ? path.slice(slash + 1) : path
}

function runningLabelFor(child: AggregateChild): string {
  switch (child.tool) {
    case 'read': return `reading ${shortBasename(child.file)}`
    case 'grep': return 'grepping'
    case 'ls':   return `listing ${shortBasename(child.path)}`
  }
}

function findRunningChild(children: AggregateChild[]): AggregateChild | undefined {
  return children.find(c => c.inFlight)
}

function groupChildrenByTool(children: AggregateChild[]): {
  read: AggregateReadChild[]; grep: AggregateGrepChild[]; ls: AggregateLsChild[]
} {
  const read: AggregateReadChild[] = []
  const grep: AggregateGrepChild[] = []
  const ls: AggregateLsChild[] = []
  for (const c of children) {
    if (c.tool === 'read') read.push(c)
    else if (c.tool === 'grep') grep.push(c)
    else ls.push(c)
  }
  return { read, grep, ls }
}

function readMetaLines(children: AggregateReadChild[]): string[] {
  let totalLines = 0
  let totalBytes = 0
  let anyLineMetric = false
  const files = new Set<string>()
  for (const c of children) {
    if (c.linesRead != null) { totalLines += c.linesRead; anyLineMetric = true }
    if (c.bytesRead != null) { totalBytes += c.bytesRead }
    files.add(c.file)
  }
  const lines: string[] = []
  if (anyLineMetric) {
    lines.push(totalBytes > 0
      ? `${totalLines} lines · ${formatBytes(totalBytes)}`
      : `${totalLines} lines`)
  }
  if (files.size !== children.length) {
    // More than one read hit the same file — worth mentioning file count.
    lines.push(`${files.size} ${files.size === 1 ? 'file' : 'files'} touched`)
  }
  return lines
}

function grepMetaLines(children: AggregateGrepChild[]): string[] {
  let totalMatches = 0
  let totalFiles = 0
  let anyMetric = false
  for (const c of children) {
    if (c.matches != null) { totalMatches += c.matches; anyMetric = true }
    if (c.filesMatched != null) { totalFiles += c.filesMatched }
  }
  const lines: string[] = []
  if (anyMetric) lines.push(`${totalMatches} matches`)
  if (totalFiles > 0) lines.push(`${totalFiles} ${totalFiles === 1 ? 'file' : 'files'} searched`)
  return lines
}

function lsMetaLines(children: AggregateLsChild[]): string[] {
  let totalEntries = 0
  let totalDirs = 0
  let anyMetric = false
  for (const c of children) {
    if (c.entries != null) { totalEntries += c.entries; anyMetric = true }
    if (c.directories != null) totalDirs += c.directories
  }
  const lines: string[] = []
  if (anyMetric) lines.push(`${totalEntries} entries`)
  if (totalDirs > 0) lines.push(`${totalDirs} ${totalDirs === 1 ? 'directory' : 'directories'}`)
  return lines
}

function aggregateElapsedMs(agg: ToolAggregateEntry, nowMs: number): number {
  const running = findRunningChild(agg.children)
  if (running) {
    return Math.max(0, nowMs - agg.startedAtMs)
  }
  let latest = agg.startedAtMs
  for (const c of agg.children) {
    if (c.completedAtMs != null && c.completedAtMs > latest) latest = c.completedAtMs
  }
  return Math.max(0, latest - agg.startedAtMs)
}

function renderAggregate(entry: ToolAggregateEntry, i: number) {
  const children = entry.children
  if (children.length === 0) return null

  // Single-child aggregates render as a standalone ToolCallRow, matching the
  // pre-aggregation visual for the common case where no grouping has happened
  // yet. The row upgrades to a card on the next consecutive exploration tool.
  if (children.length === 1) {
    const c = children[0]
    return (
      <ToolCallRow
        key={i}
        tool={c.tool}
        command={childCommand(c)}
        status={c.inFlight ? 'running' : 'done'}
        metric={childMetric(c)}
      />
    )
  }

  // Two or more children: render the full two-pane aggregate card.
  const groups = groupChildrenByTool(children)
  const running = findRunningChild(children)
  const runningLabel = running ? runningLabelFor(running) : undefined
  const elapsedMs = aggregateElapsedMs(entry, Date.now())

  const stats = [
    groups.read.length > 0 && (
      <ToolStatBlock
        key="read"
        type="read"
        name="read"
        opCount={pluralizeOps(groups.read.length)}
        metaLines={readMetaLines(groups.read)}
        active={running?.tool === 'read'}
      />
    ),
    groups.grep.length > 0 && (
      <ToolStatBlock
        key="grep"
        type="grep"
        name="grep"
        opCount={pluralizeOps(groups.grep.length)}
        metaLines={grepMetaLines(groups.grep)}
        active={running?.tool === 'grep'}
      />
    ),
    groups.ls.length > 0 && (
      <ToolStatBlock
        key="ls"
        type="ls"
        name="ls"
        opCount={pluralizeOps(groups.ls.length)}
        metaLines={lsMetaLines(groups.ls)}
        active={running?.tool === 'ls'}
      />
    ),
  ].filter(Boolean)

  const logRows = children.map((c, j) => (
    <ToolLogRow
      key={j}
      status={c.inFlight ? 'running' : c.tool}
      command={childCommand(c)}
      metric={c.inFlight
        ? (c.tool === 'read' ? 'reading…' : c.tool === 'grep' ? 'grepping…' : 'listing…')
        : childMetric(c)}
    />
  ))

  return (
    <ToolAggregateCard
      key={i}
      operationCount={children.length}
      runningLabel={runningLabel}
      elapsed={elapsedMs > 0 ? formatElapsed(elapsedMs) : undefined}
      statsPane={stats}
      logPane={logRows}
    />
  )
}

function renderEntry(entry: ConversationEntry, i: number) {
  switch (entry.type) {
    case 'thinking':
      return <ThinkingBlock key={i}><Md>{entry.content}</Md></ThinkingBlock>
    case 'text':
      return <ProseCard key={i}><Md>{entry.text}</Md></ProseCard>
    case 'tool_aggregate':
      return renderAggregate(entry, i)
    case 'tool_write':
      return <ToolCallRow key={i} tool="write" command={entry.file} status={entry.inFlight ? 'running' : 'done'} />
    case 'tool_edit':
      return <ToolCallRow key={i} tool="edit" command={entry.file} status={entry.inFlight ? 'running' : 'done'} />
    case 'tool_bash':
      return <ToolCallRow key={i} tool="bash" command={entry.command} status={entry.inFlight ? 'running' : 'done'} />
    case 'tool_generic': {
      if (SUPPRESSED_TOOLS.has(entry.toolName)) return null
      const label = KOAN_TOOL_LABELS[entry.toolName] ?? entry.toolName
      const cmd = entry.toolName in KOAN_TOOL_LABELS ? '' : entry.summary
      return <ToolCallRow key={i} tool={label} command={cmd} status={entry.inFlight ? 'running' : 'done'} />
    }
    case 'step':
      return <StepHeader key={i} stepNumber={entry.step} totalSteps={entry.totalSteps ?? 0} stepName={entry.stepName} />
    case 'debug_step_guidance':
      return <StepGuidancePill key={i} status="active" defaultExpanded={false}><Md>{entry.content}</Md></StepGuidancePill>
    case 'user_message': {
      const ts = new Date(entry.timestampMs).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      return <UserBubble key={i} timestamp={ts}><Md>{entry.content}</Md></UserBubble>
    }
    case 'phase_boundary':
      return <PhaseMarker key={i} name={entry.phase} description={entry.description || entry.message} />
    case 'yield': {
      const setChatDraft = useStore.getState().setChatDraft
      return (
        <YieldPanel
          key={i}
          prompt={entry.prompt || 'What would you like to do next?'}
          suggestions={entry.suggestions}
          onSelect={s => setChatDraft(s.command ? `/${s.id} ${s.command}` : `/${s.id} `)}
        />
      )
    }
    default:
      return null
  }
}

function ConnectedSteeringBar() {
  const steering = useStore(s => s.run?.steering ?? [])
  return <SteeringBar messages={steering.map(m => m.content)} />
}

function ContentStream() {
  const focusAgentId = useStore(s => s.run?.focus?.agentId)
  const conversation = useStore(s => focusAgentId ? s.run?.agents?.[focusAgentId]?.conversation : undefined)
  const run = useStore(s => s.run)
  const focus = useStore(s => s.run?.focus)
  const scrollRef = useRef<HTMLDivElement>(null)
  const [paletteOpen, setPaletteOpen] = useState(false)
  useAutoScroll(scrollRef)
  const hasEntries = !!(conversation?.entries?.length)
  const isWaiting = !hasEntries && !conversation?.isThinking && !conversation?.pendingText
  const hasInteraction = focus && focus.type !== 'conversation'
  const showFeedback = run !== null && !hasInteraction
  return (
    <div className="content-column" ref={scrollRef}>
      <div className={`content-stream${paletteOpen ? ' content-stream--faded' : ''}`}>
        {isWaiting && (
          <div className="waiting-indicator">
            <span className="pulse-dot">●</span>
            <span>Starting agent…</span>
          </div>
        )}
        {conversation?.entries.map(renderEntry)}
        {conversation?.isThinking && conversation.pendingThinking && (
          <ThinkingBlock defaultExpanded={true}><Md>{conversation.pendingThinking}</Md></ThinkingBlock>
        )}
        {conversation?.isThinking && !conversation.pendingThinking && (
          <div className="thinking-indicator">
            <span className="pulse-dot">●</span>
            <span>Thinking…</span>
          </div>
        )}
        {conversation?.pendingText && (
          <ProseCard><Md>{conversation.pendingText}</Md><span className="stream-cursor" /></ProseCard>
        )}
        {showFeedback && (
          <>
            <ConnectedSteeringBar />
            <FeedbackInput
              onSend={msg => api.sendChatMessage(msg)}
              disabled={!!run?.completion}
              availableCommands={run?.activeYield ? run.availablePhases : undefined}
              onPaletteToggle={setPaletteOpen}
            />
          </>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Elicitation view — fully replaces AskWizard
// ---------------------------------------------------------------------------

function isFreeText(q: AskQuestion): boolean {
  return q.free_text === true || !q.options || q.options.length === 0
}

function ElicitationView() {
  const focus = useStore(s => s.run?.focus)
  const [currentIdx, setCurrentIdx] = useState(0)
  const [answers, setAnswers] = useState<Record<number, string | string[] | null>>({})
  const [otherTexts, setOtherTexts] = useState<Record<number, string>>({})
  const [submitError, setSubmitError] = useState<string | null>(null)

  if (!focus || focus.type !== 'question') return null
  const { questions, token } = focus
  const total = questions.length
  const q = questions[currentIdx]
  const opts = normalizeOptions(q.options as (string | Record<string, unknown>)[])
  const freeText = isFreeText(q)
  const multi = q.multi

  const optionEntries = [
    ...opts.map(o => ({ label: o.label, recommended: o.recommended })),
    ...(!freeText ? [{ label: 'Other (type your own)', isCustom: true }] : []),
  ]

  const answer = answers[currentIdx] ?? null
  const selected = Array.isArray(answer) ? answer : answer ? [answer] : []

  const selectedIndex = (!multi && !freeText)
    ? (() => {
        const idx = optionEntries.findIndex((_, i) => {
          if (i < opts.length) return selected.includes(opts[i].value)
          return selected.includes('__other__')
        })
        return idx >= 0 ? idx : null
      })()
    : null

  const selectedIndices = multi
    ? optionEntries.map((_, i) => {
        const val = i < opts.length ? opts[i].value : '__other__'
        return selected.includes(val) ? i : -1
      }).filter(i => i >= 0)
    : []

  const handleSelect = (idx: number) => {
    const val = idx < opts.length ? opts[idx].value : '__other__'
    setAnswers(prev => ({ ...prev, [currentIdx]: selected[0] === val ? null : val }))
  }

  const handleToggle = (idx: number) => {
    const val = idx < opts.length ? opts[idx].value : '__other__'
    const newSel = selected.includes(val) ? selected.filter(v => v !== val) : [...selected, val]
    setAnswers(prev => ({ ...prev, [currentIdx]: newSel }))
  }

  const handleFreeTextChange = (text: string) => {
    setAnswers(prev => ({ ...prev, [currentIdx]: text || null }))
  }

  const handleCustomTextChange = (text: string) => {
    setOtherTexts(prev => ({ ...prev, [currentIdx]: text }))
  }

  const resolveAnswers = () => {
    return questions.map((_, i) => {
      const raw = answers[i] ?? null
      const typed = otherTexts[i] || ''
      if (raw === '__other__') return typed || null
      if (Array.isArray(raw)) return raw.map(v => v === '__other__' ? typed : v)
      return raw
    })
  }

  const handleSubmit = async () => {
    if (currentIdx < total - 1) { setCurrentIdx(i => i + 1); return }
    const final = resolveAnswers()
    const res = await api.submitAnswer(final, token)
    if (!res.ok) setSubmitError(res.message ?? 'Failed to submit answers')
  }

  const handleUseDefaults = async () => {
    const defaults = questions.map(qq => {
      if (isFreeText(qq)) return null
      const rec = (qq.options ?? []).filter(o => o.recommended).map(o => o.value)
      return qq.multi ? rec : (rec[0] ?? null)
    })
    const res = await api.submitAnswer(defaults, token)
    if (!res.ok) setSubmitError(res.message ?? 'Failed to submit defaults')
  }

  const mode = freeText ? 'free-text' : multi ? 'multi-select' : 'single-select'

  return (
    <ElicitationPanel
      context={q.context ? <Md>{q.context}</Md> : undefined}
      question={q.question}
      options={optionEntries}
      mode={mode as 'single-select' | 'multi-select' | 'free-text'}
      selectedIndex={selectedIndex}
      onSelect={handleSelect}
      selectedIndices={selectedIndices}
      onToggle={handleToggle}
      freeText={freeText ? (typeof answer === 'string' ? answer : '') : undefined}
      onFreeTextChange={freeText ? handleFreeTextChange : undefined}
      customText={otherTexts[currentIdx] ?? ''}
      onCustomTextChange={handleCustomTextChange}
      questionNumber={currentIdx + 1}
      totalQuestions={total}
      showPrevious={currentIdx > 0}
      onPrevious={() => setCurrentIdx(i => i - 1)}
      onSubmit={handleSubmit}
      onUseDefaults={handleUseDefaults}
      error={submitError}
    />
  )
}

// ---------------------------------------------------------------------------
// Completion
// ---------------------------------------------------------------------------

function CompletionView() {
  const completion = useStore(s => s.run?.completion)
  const artifacts = useStore(s => s.run?.artifacts ?? {})
  if (!completion) return null
  return (
    <div className="content-column">
      <div className="content-stream">
        {completion.success ? (
          <>
            <CompletionBanner>{completion.summary || 'All phases completed successfully.'}</CompletionBanner>
            {Object.keys(artifacts).length > 0 && (
              <ProseCard>
                <p><strong>Artifacts produced:</strong></p>
                <ul>{Object.keys(artifacts).map(p => <li key={p}><code>{p}</code></li>)}</ul>
              </ProseCard>
            )}
          </>
        ) : (
          <CompletionBanner variant="error">{completion.error || 'An error occurred.'}</CompletionBanner>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Navigation items
// ---------------------------------------------------------------------------

const NAV_ITEMS = [
  { label: 'New run', key: 'new-run' },
  { label: 'Sessions', key: 'sessions' },
  { label: 'Settings', key: 'settings' },
]

// ---------------------------------------------------------------------------
// Settings page wiring
// ---------------------------------------------------------------------------

function ConnectedSettingsPage() {
  const profilesDict = useStore(s => s.settings.profiles)
  const installationsDict = useStore(s => s.settings.installations)
  const scoutConcurrency = useStore(s => s.settings.defaultScoutConcurrency)
  const [probeData, setProbeData] = useState<api.RunnerInfo[]>([])

  useEffect(() => {
    api.getProbeInfo()
      .then(data => setProbeData(data.runners))
      .catch(() => {}) /* probe failure is non-fatal — dropdowns stay empty */
  }, [])

  const profiles: SPProfile[] = useMemo(() =>
    Object.values(profilesDict).map(p => ({
      id: p.name,
      name: p.name,
      locked: p.readOnly,
      tiers: {
        /* TODO: model and thinking are not in the store wire format —
           the backend profile tiers map role → installation alias.
           We resolve the runner from the installation but model/thinking
           are managed backend-side and not exposed in SSE state yet. */
        strong: { runner: installationsDict[p.tiers['strong']]?.runnerType || p.tiers['strong'] || '', model: '', thinking: '' },
        standard: { runner: installationsDict[p.tiers['standard']]?.runnerType || p.tiers['standard'] || '', model: '', thinking: '' },
        cheap: { runner: installationsDict[p.tiers['cheap']]?.runnerType || p.tiers['cheap'] || '', model: '', thinking: '' },
      },
    })),
    [profilesDict, installationsDict],
  )

  const installations: SPInstallation[] = useMemo(() =>
    Object.values(installationsDict).map(i => ({
      id: i.alias,
      alias: i.alias,
      runner: i.runnerType,
      binary: i.binary,
      extraArgs: i.extraArgs.join(' '),
      isDefault: i.alias.endsWith('-default'),
      available: i.available,
    })),
    [installationsDict],
  )

  const runnerTypes = useMemo(() => {
    // Prefer probe data (includes runners without installations); fall back to installed
    if (probeData.length > 0) return probeData.map(r => r.runner_type).sort()
    const types = new Set(Object.values(installationsDict).map(i => i.runnerType))
    return [...types].sort()
  }, [probeData, installationsDict])

  const runnerOptions = useMemo(() =>
    runnerTypes.map(r => ({ value: r, label: r })),
    [runnerTypes],
  )

  const modelOptionsForRunner = useMemo(() =>
    (runner: string) => {
      const info = probeData.find(r => r.runner_type === runner)
      return info?.models.map(m => ({ value: m.alias, label: m.display_name })) ?? []
    },
    [probeData],
  )

  const thinkingOptionsForModel = useMemo(() =>
    (runner: string, model: string) => {
      const info = probeData.find(r => r.runner_type === runner)
      const modelInfo = info?.models.find(m => m.alias === model)
      if (modelInfo && modelInfo.thinking_modes.length > 0) {
        return modelInfo.thinking_modes.map(t => ({ value: t, label: t }))
      }
      // Fallback when no model selected or probe data unavailable
      return [{ value: 'budget', label: 'budget' }, { value: 'medium', label: 'medium' }, { value: 'high', label: 'high' }]
    },
    [probeData],
  )

  return (
    <SettingsPage
      profiles={profiles}
      onCreateProfile={async p => {
        const tiers: Record<string, { runner_type: string; model: string; thinking: string }> = {}
        for (const [k, v] of Object.entries(p.tiers)) {
          tiers[k] = { runner_type: v.runner, model: v.model, thinking: v.thinking }
        }
        const res = await api.createProfile(p.name, tiers)
        if (!res.ok) throw new Error(res.message || 'Failed to create profile')
      }}
      onUpdateProfile={async (id, p) => {
        if (p.tiers) {
          const tiers: Record<string, { runner_type: string; model: string; thinking: string }> = {}
          for (const [k, v] of Object.entries(p.tiers)) {
            tiers[k] = { runner_type: v.runner, model: v.model, thinking: v.thinking }
          }
          const res = await api.updateProfile(id, tiers)
          if (!res.ok) throw new Error(res.message || 'Failed to update profile')
        }
      }}
      onDeleteProfile={id => api.deleteProfile(id)}
      installations={installations}
      runnerTypes={runnerTypes}
      onCreateInstallation={async inst => {
        const res = await api.createAgent({
          alias: inst.alias,
          runner_type: inst.runner,
          binary: inst.binary,
          extra_args: inst.extraArgs ? inst.extraArgs.split(' ').filter(Boolean) : [],
        })
        if (!res.ok) throw new Error(res.message || 'Failed to create installation')
      }}
      onUpdateInstallation={async (id, inst) => {
        const res = await api.updateAgent(id, {
          ...(inst.runner && { runner_type: inst.runner }),
          ...(inst.binary && { binary: inst.binary }),
          ...(inst.extraArgs !== undefined && { extra_args: inst.extraArgs.split(' ').filter(Boolean) }),
        })
        if (!res.ok) throw new Error(res.message || 'Failed to update installation')
      }}
      onDeleteInstallation={id => api.deleteAgent(id)}
      onDetectBinary={async runner => {
        const res = await api.detectAgent(runner)
        return res.path
      }}
      scoutConcurrency={scoutConcurrency}
      onScoutConcurrencyChange={n => api.saveScoutConcurrency(n)}
      runnerOptions={runnerOptions}
      modelOptionsForRunner={modelOptionsForRunner}
      thinkingOptionsForModel={thinkingOptionsForModel}
    />
  )
}

// ---------------------------------------------------------------------------
// Review view — renders ReviewPanel for the currently open artifact
// ---------------------------------------------------------------------------

// DESIGN NOTE: the opener below deliberately does NOT ask the LLM to verify
// its own revision before re-yielding. Intrinsic self-correction is a
// documented anti-pattern -- the user's next review pass is the verifier,
// not the model. Do not add "double-check your edits", "validate each
// change", or any similar self-verification language.
//
// The opener also pairs with the REVIEW FEEDBACK LOOP contract documented
// in the koan_yield tool docstring (koan/web/mcp_endpoint.py). Both sides
// must stay in sync: the "I've reviewed `<path>`" sentinel is how the LLM
// recognizes the payload as a review response.
//
// Three response types:
//   1. Approval  -- no comments, no summary -> "approve it as-is"
//   2. Structured -- inline comments (+ optional summary)
//   3. Free-form  -- summary only, no inline comments
function formatReviewMessage(path: string, payload: ReviewSubmitPayload): string {
  const summary = payload.summary.trim()
  const hasComments = payload.comments.length > 0
  const hasSummary = summary.length > 0

  // Approval -- no comments and no summary means the artifact is accepted.
  if (!hasComments && !hasSummary) {
    return `I've reviewed \`${path}\` and approve it as-is. No changes requested.`
  }

  const out: string[] = []

  // Structured feedback -- inline comments (with optional summary).
  if (hasComments) {
    out.push(
      `I've reviewed \`${path}\`. For each inline comment below, edit the cited section of the file to address it. Preserve everything not called out. When all comments are addressed, call \`koan_yield\` again so I can confirm or give another pass.`,
    )

    // Group comments by blockIndex in document order.
    const groups = new Map<number, { preview: string; comments: string[] }>()
    for (const c of payload.comments) {
      const g = groups.get(c.blockIndex)
      if (g) g.comments.push(c.text)
      else groups.set(c.blockIndex, { preview: c.blockPreview, comments: [c.text] })
    }
    const sorted = [...groups.entries()].sort(([a], [b]) => a - b)

    for (const [, g] of sorted) {
      out.push('')
      out.push('On the section:')
      for (const line of g.preview.split('\n')) out.push(`> ${line}`)
      out.push('')
      for (const text of g.comments) {
        const parts = text.split('\n')
        out.push(`- ${parts[0]}`)
        for (let i = 1; i < parts.length; i++) out.push(`  ${parts[i]}`)
      }
    }
  }

  // Free-form feedback -- summary only, no inline comments.
  if (!hasComments && hasSummary) {
    out.push(
      `I've reviewed \`${path}\`. Apply the feedback below, then call \`koan_yield\` again so I can confirm or give another pass.`,
    )
  }

  if (hasSummary) {
    out.push('')
    out.push(`**Summary:** ${summary}`)
  }

  return out.join('\n')
}

function ReviewView() {
  const path = useStore(s => s.reviewingArtifact)
  const setReviewing = useStore(s => s.setReviewingArtifact)
  const [content, setContent] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!path) return
    setContent(null)
    setError(null)
    let cancelled = false
    api.getArtifactContent(path)
      .then(res => { if (!cancelled) setContent(res.content) })
      .catch(e => { if (!cancelled) setError(String(e)) })
    return () => { cancelled = true }
  }, [path])

  if (!path) return null

  const handleSubmit = (payload: ReviewSubmitPayload) => {
    const message = formatReviewMessage(path, payload)
    console.log('[review] submitting:\n' + message)
    api.sendChatMessage(message)
    setReviewing(null)
  }

  return (
    <div className="content-column" style={{ padding: '28px 32px 40px 32px' }}>
      {content === null && !error && <div className="loading-center">loading…</div>}
      {error && <div className="loading-center">Error: {error}</div>}
      {content !== null && (
        <ReviewPanel
          path={path}
          content={content}
          onSubmit={handleSubmit}
          onClose={() => setReviewing(null)}
        />
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

export default function App() {
  const run = useStore(s => s.run)
  const connected = useStore(s => s.connected)
  const reviewingArtifact = useStore(s => s.reviewingArtifact)
  const activeYield = useStore(s => s.run?.activeYield ?? null)
  const artifactsDict = useStore(s => s.run?.artifacts)
  const header = useHeaderData()
  const [page, setPage] = useState<'new-run' | 'sessions' | 'settings'>('new-run')

  // Review auto-open: yield-triggered, not write-triggered. Fires when the
  // orchestrator parks in koan_yield -- the synchronous checkpoint where a
  // review is expected. Picks the newest .md artifact modified since the
  // previous yield (or since app mount for the first yield). If no .md was
  // modified in that window, no auto-open (the yield is not about an artifact).
  // TODO: gate behind settings toggle "Auto-open new or changed artifacts".
  const lastYieldAtRef = useRef<number>(Date.now())
  useEffect(() => {
    if (activeYield === null) return
    const cutoff = lastYieldAtRef.current
    lastYieldAtRef.current = Date.now()
    const candidates = Object.values(artifactsDict ?? {})
      .filter(a => a.path.endsWith('.md') && a.modifiedAt > cutoff)
    if (candidates.length === 0) return
    const newest = candidates.reduce((a, b) => (a.modifiedAt >= b.modifiedAt ? a : b))
    useStore.getState().setReviewingArtifact(newest.path)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeYield])

  useEffect(() => {
    let es: EventSource | null = null
    let retryDelay = 500
    function connect() {
      es = connectSSE(useStore)
      es.onerror = () => {
        useStore.getState().setConnected(false)
        es?.close()
        setTimeout(connect, retryDelay)
        retryDelay = Math.min(retryDelay * 2, 5000)
      }
      es.onopen = () => { retryDelay = 500 }
    }
    connect()
    return () => { es?.close() }
  }, [])

  const goToSettings = () => setPage('settings')
  const focus = run?.focus
  const hasInteraction = focus && focus.type !== 'conversation'
  const completion = run?.completion

  // --- Loading ---
  if (!connected) {
    return (
      <div className="app-root">
        <HeaderBar phase="" step="" totalSteps={0} currentStep={0} />
        <div className="single-column"><div className="loading-center">connecting…</div></div>
      </div>
    )
  }

  // --- No active run: page navigation ---
  if (!run) {
    return (
      <div className="app-root">
        <HeaderBar
          phase="" step="" totalSteps={0} currentStep={0}
          mode="navigation"
          navItems={NAV_ITEMS}
          activeNav={page}
          onNavChange={k => setPage(k as typeof page)}
        />
        {page === 'new-run' && <div className="single-column"><NewRunForm /></div>}
        {page === 'sessions' && (
          <div className="single-column">
            <SessionsPage />
          </div>
        )}
        {page === 'settings' && <ConnectedSettingsPage />}
        <Notification />
      </div>
    )
  }

  // --- Active run: workflow views ---
  if (hasInteraction) {
    return (
      <div className="app-root">
        <HeaderBar {...header} onSettingsClick={goToSettings} />
        <div className="workflow-grid">
          <div className="content-column"><ElicitationView /></div>
          <ConnectedSidebar />
        </div>
        <Notification />
      </div>
    )
  }

  if (completion) {
    return (
      <div className="app-root">
        <HeaderBar {...header} onSettingsClick={goToSettings} />
        <div className="workflow-grid"><CompletionView /><ConnectedSidebar /></div>
        <Notification />
      </div>
    )
  }

  if (reviewingArtifact) {
    return (
      <div className="app-root">
        <HeaderBar {...header} onSettingsClick={goToSettings} />
        <div className="workflow-grid"><ReviewView /><ConnectedSidebar /></div>
        <ConnectedScoutBar />
        <Notification />
      </div>
    )
  }

  return (
    <div className="app-root">
      <HeaderBar {...header} onSettingsClick={goToSettings} />
      <div className="workflow-grid"><ContentStream /><ConnectedSidebar /></div>
      <ConnectedScoutBar />
      <Notification />
    </div>
  )
}
