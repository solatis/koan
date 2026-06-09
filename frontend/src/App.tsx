/*
 * EVENT TYPE -> MOLECULE MAPPING (final, no gaps)
 * -------------------------------------------------
 * thinking             -> ThinkingBlock + Md
 * text                 -> ProseCard + Md
 * tool_write/edit      -> ToolCallRow
 * tool_bash            -> ToolCallRow
 * tool_generic         -> ToolCallRow (rare; non-koan custom tools only)
 * tool_koan            -> KoanToolCard (dispatches by toolName;
 *                          koan_complete_step and koan_set_phase
 *                          suppressed inside the card)
 * step                 -> StepHeader
 * debug_step_guidance  -> StepGuidancePill + Md
 * user_message         -> UserBubble + Md
 * phase_boundary       -> PhaseMarker
 * yield                -> YieldPanel
 * pendingThinking      -> ThinkingBlock (always expanded)
 * pendingText          -> ProseCard + Md + streaming cursor
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'
import { useStore, ConversationEntry, AskQuestion, CompletionInfo } from './store/index'
// DEBUG: expose store to window for browser-agent introspection
;(window as unknown as { __store: typeof useStore }).__store = useStore
import { connectSSE } from './sse/connect'
import { useElapsed, formatElapsed } from './hooks/useElapsed'
import { useAutoScroll } from './hooks/useAutoScroll'
import { normalizeOptions } from './utils'
import * as api from './api/client'

import { Button } from './components/atoms/Button'
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
// ArtifactReviewPin deleted in M6 (koan_artifact_propose removed in M5).
import { KoanToolCard } from './components/molecules/KoanToolCard'

import { Md } from './components/Md'
import { Notification } from './components/Notification'
// Installation type removed in M4: agent installation concept deleted.
import { SettingsPage, type Profile as SPProfile, type ProviderConfigView } from './components/organisms/SettingsPage'
import { ReviewPanel } from './components/organisms/ReviewPanel'
import { SessionsPage } from './components/organisms/SessionsPage'
import { MemoryRoutes } from './components/organisms/MemoryRoutes'
import { CurationTakeover } from './components/organisms/CurationTakeover'

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
    usage: primary
      ? {
          inputTokens: primary.conversation.inputTokens,
          outputTokens: primary.conversation.outputTokens,
          cacheReadTokens: primary.conversation.cacheReadTokens,
          cacheWriteTokens: primary.conversation.cacheWriteTokens,
          totalCostUsd: primary.conversation.totalCostUsd,
          contextWindowPercent: primary.conversation.contextWindowPercent,
        }
      : undefined,
  }
}

// ---------------------------------------------------------------------------
// Sidebar + scout bar wiring
// ---------------------------------------------------------------------------

function ConnectedSidebar() {
  const artifacts = useStore(s => s.run?.artifacts ?? {})
  const reviewingArtifact = useStore(s => s.reviewingArtifact)
  const setReviewingArtifact = useStore(s => s.setReviewingArtifact)
  // lastTouchpointMs is null until the first yield resolves; all artifacts show
  // as "changed" in that initial state, which is the intended behaviour.
  const lastTouchpointMs = useStore(s => s.lastTouchpointMs)
  const entries = useMemo(() => {
    const now = Date.now()
    const list = Object.values(artifacts).map(a => {
      const mins = Math.floor((now - a.modifiedAt) / 60000)
      return {
        path: a.path,
        filename: a.path.split('/').pop() || a.path,
        modifiedAgo: mins < 1 ? 'just now' : mins < 60 ? `modified ${mins}m ago` : `modified ${Math.floor(mins / 60)}h ago`,
        variant: mins < 5 ? ('recent' as const) : ('stable' as const),
        changed: a.modifiedAt > (lastTouchpointMs ?? 0),
        _ts: a.modifiedAt,
      }
    })
    list.sort((a, b) => b._ts - a._ts)
    return list.map(({ path, filename, modifiedAgo, variant, changed }) => ({ path, filename, modifiedAgo, variant, changed }))
  }, [artifacts, lastTouchpointMs])
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

// SUPPRESSED_TOOLS and KOAN_TOOL_LABELS moved into KoanToolCard in M2 of
// unify-tool-lifecycle: post-M1, every koan MCP tool creates ToolKoanEntry
// (not ToolGenericEntry), so the old SUPPRESSED_TOOLS check on entry.toolName
// for tool_generic entries was dead code. Suppression and labels now live
// co-located with the per-tool dispatch in KoanToolCard.

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
      return <ToolCallRow key={i} tool="write" command={entry.file} status={entry.inFlight ? 'running' : 'done'} attachments={entry.attachments} />
    case 'tool_edit':
      return <ToolCallRow key={i} tool="edit" command={entry.file} status={entry.inFlight ? 'running' : 'done'} attachments={entry.attachments} />
    case 'tool_bash':
      return <ToolCallRow key={i} tool="bash" command={entry.command} status={entry.inFlight ? 'running' : 'done'} attachments={entry.attachments} />
    // tool_generic is reached only by non-koan custom tools post-M1;
    // koan MCP tools now create ToolKoanEntry via the broadened KOAN_MCP_TOOLS set.
    case 'tool_generic':
      return <ToolCallRow key={i} tool={entry.toolName} command={entry.summary} status={entry.inFlight ? 'running' : 'done'} attachments={entry.attachments} />
    case 'tool_koan':
      // toolInput is the M1 aggregate field for live partial-args rendering.
      // Passed alongside args so ReflectCard (which reads args) continues
      // to work unchanged until M3 refactors ToolKoanEntry split-source.
      return (
        <KoanToolCard
          key={i}
          toolName={entry.toolName}
          args={entry.args}
          toolInput={entry.toolInput ?? null}
          result={entry.result}
          inFlight={entry.inFlight}
        />
      )
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
      const state = useStore.getState()
      const setChatDraft = state.setChatDraft
      // Compute changed artifacts at render time using the imperative store API.
      // By the time lastTouchpointMs updates (on chat send), this yield entry is
      // replaced by a user_message entry so stale changedArtifacts are never seen.
      const ltp = state.lastTouchpointMs
      const changedArtifacts = Object.values(state.run?.artifacts ?? {})
        .filter(a => a.modifiedAt > (ltp ?? 0))
        .map(a => a.path)
      return (
        <YieldPanel
          key={i}
          prompt={entry.prompt || 'What would you like to do next?'}
          suggestions={entry.suggestions}
          changedArtifacts={changedArtifacts}
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
  // Read from settings.workflows (static, populated at server startup) rather than
  // run.availableWorkflows, which was removed in favour of a single source of truth.
  const workflows = useStore(s => s.settings.workflows)
  // reviewingArtifact used only by ArtifactReviewPin (deleted in M6); kept as
  // context for the "already reviewing" guard if re-added in a future milestone.
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
            {/* ArtifactReviewPin removed in M6 -- koan_artifact_propose deleted in M5. */}
            <FeedbackInput
              onSend={(msg, attachments) => {
                // Mark yield resolution so sidebar and yield panel reflect the new
                // "changed since last touchpoint" baseline going forward.
                useStore.getState().setLastTouchpointMs(Date.now())
                return api.sendChatMessage(msg, attachments)
              }}
              disabled={!!run?.completion}
              availableCommands={
                run?.activeYield
                  ? [
                      ...run.availablePhases,
                      // Workflow commands use "workflow:<name>" IDs (colon, not space)
                      // so the palette's startsWith filter works and no space breaks
                      // the paletteOpen guard in FeedbackInput.
                      ...workflows.map(w => ({
                        id: `workflow:${w.id}`,
                        description: `Switch to ${w.id} workflow${w.description ? ` -- ${w.description}` : ''}`,
                      })),
                    ]
                  : undefined
              }
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
  // Per-question attachment IDs; collected as the user pages through questions
  // and folded into the final answer list on submit per M3 wire shape.
  const [attachmentsByIdx, setAttachmentsByIdx] = useState<Record<number, string[]>>({})
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

  const handleSubmit = async (attachments?: string[]) => {
    // Record attachments for the current question before advancing or submitting.
    if (attachments && attachments.length > 0) {
      setAttachmentsByIdx(prev => ({ ...prev, [currentIdx]: attachments }))
    }
    if (currentIdx < total - 1) { setCurrentIdx(i => i + 1); return }
    // Wrap each resolved answer as {answer, attachments?} per M3 wire shape.
    // Use the just-received attachments for the final question rather than
    // the stale state entry (state update is async).
    const final = resolveAnswers().map((ans, i) => {
      const a = i === currentIdx ? attachments : attachmentsByIdx[i]
      if (a && a.length > 0) return { answer: ans, attachments: a }
      return { answer: ans }
    })
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

function CompletionView(props: { onBackToOverview?: () => void }) {
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
          <>
            <CompletionBanner variant="error">{completion.error || 'An error occurred.'}</CompletionBanner>
            {props.onBackToOverview && (
              <div className="completion-actions">
                {/* Button visible only on failure; success auto-navigates on a timer. */}
                <Button variant="secondary" onClick={props.onBackToOverview}>Back to overview</Button>
              </div>
            )}
          </>
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
  { label: 'Memory', key: 'memory' },
  { label: 'Settings', key: 'settings' },
]

// Maps nav keys to URL paths for URL-driven navigation.
const PATH_BY_KEY: Record<string, string> = {
  'new-run': '/',
  sessions: '/sessions',
  memory: '/memory',
  settings: '/settings',
}

// ---------------------------------------------------------------------------
// Settings page wiring
// ---------------------------------------------------------------------------

/**
 * ConnectedSettingsPage -- wires the store and API client to the presentational
 * SettingsPage organism. Also wires provider configuration (M4): maps
 * providerStatus to ProviderConfigView and threads onSaveProvider /
 * onDeleteProvider through the unified /api/settings/provider endpoints.
 * The dynamic provider model overlay (providerModels) is unioned into
 * modelOptionsForRunner so LM Studio and other overlay models are selectable.
 */
function ConnectedSettingsPage() {
  // Runner/model/thinking options come from the model registry in the projection
  // store (populated by initial events at startup). M4: installationsDict removed.
  const profilesDict = useStore(s => s.settings.profiles)
  const scoutConcurrency = useStore(s => s.settings.defaultScoutConcurrency)
  const modelRegistry = useStore(s => s.settings.modelRegistry)
  const providerStatus = useStore(s => s.settings.providerStatus)
  const providerModels = useStore(s => s.settings.providerModels)

  const profiles: SPProfile[] = useMemo(() =>
    Object.values(profilesDict).map(p => ({
      id: p.name,
      name: p.name,
      locked: p.readOnly,
      tiers: {
        // M3: tiers are now {provider, model, thinking}; map provider -> runner for SettingsPage.
        strong:   { runner: p.tiers['strong']?.provider   || '', model: p.tiers['strong']?.model   || '', thinking: p.tiers['strong']?.thinking   || '' },
        standard: { runner: p.tiers['standard']?.provider || '', model: p.tiers['standard']?.model || '', thinking: p.tiers['standard']?.thinking || '' },
        cheap:    { runner: p.tiers['cheap']?.provider    || '', model: p.tiers['cheap']?.model    || '', thinking: p.tiers['cheap']?.thinking    || '' },
      },
    })),
    [profilesDict],
  )

  // Map store providerStatus to the presentational ProviderConfigView shape.
  // region/baseUrl arrive via provider_status_listed JSON Patch (M3 backend).
  const providers: ProviderConfigView[] = useMemo(() =>
    providerStatus.map(ps => ({
      provider: ps.provider,
      available: ps.available,
      region: ps.region ?? null,
      baseUrl: ps.baseUrl ?? null,
    })),
    [providerStatus],
  )

  // Runner types: union of static registry and dynamic overlay providers.
  const runnerTypes = useMemo(() => {
    const all = new Set([
      ...modelRegistry.map(e => e.provider),
      ...providerModels.map(e => e.provider),
    ])
    return [...all].sort()
  }, [modelRegistry, providerModels])

  const runnerOptions = useMemo(() =>
    runnerTypes.map(r => ({ value: r, label: r })),
    [runnerTypes],
  )

  const modelOptionsForRunner = useMemo(() =>
    (runner: string) => {
      const staticOpts = modelRegistry
        .filter(e => e.provider === runner)
        .map(e => ({ value: e.model, label: e.displayName || e.model }))
      const staticModels = new Set(staticOpts.map(o => o.value))
      // Append overlay models for this runner, deduping against static.
      const overlayOpts = providerModels
        .filter(e => e.provider === runner && !staticModels.has(e.model))
        .map(e => ({ value: e.model, label: e.displayName || e.model }))
      return [...staticOpts, ...overlayOpts]
    },
    [modelRegistry, providerModels],
  )

  const thinkingOptionsForModel = useMemo(() =>
    (runner: string, model: string) => {
      // Overlay-only models have no registry entry -> returns [] -> only "disabled".
      const entry = modelRegistry.find(e => e.provider === runner && e.model === model)
      if (entry && entry.thinkingModes.length > 0) {
        return entry.thinkingModes.map(t => ({ value: t, label: t }))
      }
      return []
    },
    [modelRegistry],
  )

  return (
    <SettingsPage
      profiles={profiles}
      onCreateProfile={async p => {
        // M3: map runner -> provider in the tier payload.
        const tiers: Record<string, { provider: string; model: string; thinking: string }> = {}
        for (const [k, v] of Object.entries(p.tiers)) {
          tiers[k] = { provider: v.runner, model: v.model, thinking: v.thinking }
        }
        const res = await api.createProfile(p.name, tiers)
        if (!res.ok) throw new Error(res.message || 'Failed to create profile')
      }}
      onUpdateProfile={async (id, p) => {
        if (p.tiers) {
          // M3: map runner -> provider in the tier payload.
          const tiers: Record<string, { provider: string; model: string; thinking: string }> = {}
          for (const [k, v] of Object.entries(p.tiers)) {
            tiers[k] = { provider: v.runner, model: v.model, thinking: v.thinking }
          }
          const res = await api.updateProfile(id, tiers)
          if (!res.ok) throw new Error(res.message || 'Failed to update profile')
        }
      }}
      onDeleteProfile={id => api.deleteProfile(id)}
      // installations/runnerTypes/onCreateInstallation/onUpdateInstallation/
      // onDeleteInstallation/onDetectBinary removed in M4: installation concept deleted.
      providers={providers}
      onSaveProvider={async (provider, fields) => {
        const res = await api.setProviderConfig(provider, fields)
        if (!res.ok) throw new Error(res.message || 'Failed to save provider config')
      }}
      onDeleteProvider={async provider => {
        const res = await api.deleteProviderConfig(provider)
        if (!res.ok) throw new Error(res.message || 'Failed to delete provider config')
      }}
      onTestProvider={async (provider, fields) => api.testProviderConfig(provider, fields)}
      scoutConcurrency={scoutConcurrency}
      onScoutConcurrencyChange={n => api.saveScoutConcurrency(n)}
      runnerOptions={runnerOptions}
      modelOptionsForRunner={modelOptionsForRunner}
      thinkingOptionsForModel={thinkingOptionsForModel}
    />
  )
}

// ---------------------------------------------------------------------------
// Review view -- renders ReviewPanel for the currently open artifact
// ---------------------------------------------------------------------------

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

  // Submit to /api/artifact-comment (M5 endpoint). Flat schema: path + comment
  // + attachments. The old /api/artifact-review and multi-block payload are gone.
  const handleSubmit = (comment: string, attachments: string[]) => {
    api.submitArtifactComment(path, comment, attachments)
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
  const completion = run?.completion ?? null
  const header = useHeaderData()
  const location = useLocation()
  const navigate = useNavigate()

  // Derive the active nav key from the current URL path so browser back/forward
  // updates the nav highlight without local state.
  const page: 'new-run' | 'sessions' | 'memory' | 'settings' =
    location.pathname.startsWith('/memory') ? 'memory'
    : location.pathname === '/sessions' ? 'sessions'
    : location.pathname === '/settings' ? 'settings'
    : 'new-run'

  // Auto-open effect removed in M6 -- koan_artifact_propose (and the
  // activeArtifactReview field it drove) was deleted in M5. Artifacts are
  // now opened on demand by the user clicking them in the sidebar.

  // Snapshot run.completion into lastCompletion on the null->non-null rising
  // edge only. The ref guards against re-snapshotting on every re-render or
  // on future events that re-emit the same completion object.
  const prevCompletionRef = useRef<CompletionInfo | null>(null)
  useEffect(() => {
    const current = run?.completion ?? null
    if (prevCompletionRef.current === null && current !== null) {
      useStore.getState().setLastCompletion(current)
    }
    prevCompletionRef.current = current
  }, [run?.completion])

  // Success: auto-clear + navigate after 3 seconds so the user can read the
  // completion banner before the overview appears. The timer is cancelled if
  // the component unmounts or if completion changes (e.g. SSE reconnect).
  useEffect(() => {
    if (!completion || !completion.success) return
    const timer = setTimeout(async () => {
      await api.clearRun()
      navigate('/')
    }, 3000)
    return () => clearTimeout(timer)
  }, [completion, navigate])

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

  const goToSettings = () => navigate('/settings')
  const focus = run?.focus

  // Derive sub-page breadcrumbs from the current URL for memory routes.
  const memoryCrumbs = useMemo(() => {
    if (!location.pathname.startsWith('/memory')) return undefined
    const parts = location.pathname.split('/').filter(Boolean)
    if (parts.length === 1) return undefined  // /memory itself — no crumbs
    if (parts[1] === 'reflect') {
      const q = useStore.getState().reflect?.question ?? ''
      const snip = q.length > 40 ? q.slice(0, 40) + '...' : q
      return [
        { label: 'Memory', href: '/memory' },
        { label: 'Reflect' },
        ...(snip ? [{ label: `"${snip}"` }] : []),
      ]
    }
    return [
      { label: 'Memory', href: '/memory' },
      { label: `#${parts[1]}` },
    ]
  }, [location.pathname])
  const hasInteraction = focus && focus.type !== 'conversation'

  // --- Loading ---
  if (!connected) {
    return (
      <div className="app-root">
        <HeaderBar phase="" step="" totalSteps={0} currentStep={0} />
        <div className="single-column"><div className="loading-center">connecting...</div></div>
      </div>
    )
  }

  // --- Curation takeover: supersedes all run-scoped views ---
  // Placed before hasInteraction/completion/review branches so it takes
  // priority whenever the orchestrator is blocked in koan_memory_propose.
  if (run?.activeCurationBatch) {
    return (
      <div className="app-root">
        <HeaderBar
          phase="" step="" totalSteps={0} currentStep={0}
          mode="navigation"
          navItems={NAV_ITEMS}
          activeNav=""
          crumbs={[{ label: 'Memory curation' }]}
          onNavChange={k => navigate(PATH_BY_KEY[k] ?? '/')}
        />
        <CurationTakeover />
        <Notification />
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
          crumbs={memoryCrumbs}
          onNavChange={k => navigate(PATH_BY_KEY[k] ?? '/')}
        />
        {page === 'new-run' && <div className="single-column"><NewRunForm /></div>}
        {page === 'sessions' && (
          <div className="single-column">
            <SessionsPage />
          </div>
        )}
        {page === 'memory' && <div className="single-column"><MemoryRoutes /></div>}
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
    if (completion.success) {
      // Auto-navigation timer is running (3s). Keep workflow-mode header so
      // the phase/step breadcrumb remains visible while the user waits.
      return (
        <div className="app-root">
          <HeaderBar {...header} onSettingsClick={goToSettings} />
          <div className="workflow-grid"><CompletionView /><ConnectedSidebar /></div>
          <Notification />
        </div>
      )
    }
    // Failure: switch to navigation-mode header so nav clicks can clear and
    // navigate. No auto-navigation — user must take an explicit action.
    const handleNav = async (k: string) => {
      await api.clearRun()
      navigate(PATH_BY_KEY[k] ?? '/')
    }
    const handleBack = async () => {
      await api.clearRun()
      navigate('/')
    }
    return (
      <div className="app-root">
        <HeaderBar
          phase="" step="" totalSteps={0} currentStep={0}
          mode="navigation"
          navItems={NAV_ITEMS}
          activeNav=""
          onNavChange={handleNav}
        />
        <div className="workflow-grid">
          <CompletionView onBackToOverview={handleBack} />
          <ConnectedSidebar />
        </div>
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
