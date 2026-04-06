/*
 * EVENT TYPE → MOLECULE MAPPING (final, no gaps)
 * ─────────────────────────────────────────────────
 * thinking             → ThinkingBlock + Md
 * text                 → ProseCard + Md
 * tool_read/write/edit → ToolCallRow
 * tool_bash/grep/ls    → ToolCallRow
 * tool_generic         → ToolCallRow
 * step                 → StepHeader
 * debug_step_guidance  → StepGuidancePill + Md
 * user_message         → UserBubble + Md
 * phase_boundary       → PhaseBoundary
 * pendingThinking      → ThinkingBlock (always expanded)
 * pendingText          → ProseCard + Md + streaming cursor
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { useStore, ConversationEntry, AskQuestion } from './store/index'
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
import { StepGuidancePill } from './components/molecules/StepGuidancePill'
import { FeedbackInput } from './components/molecules/FeedbackInput'
import { UserBubble } from './components/molecules/UserBubble'
import { PhaseBoundary } from './components/molecules/PhaseBoundary'
import { StepHeader } from './components/molecules/StepHeader'
import { CompletionBanner } from './components/molecules/CompletionBanner'
import { SteeringBar } from './components/molecules/SteeringBar'

import { Md } from './components/Md'
import { Notification } from './components/Notification'
import { SettingsOverlay } from './components/SettingsOverlay'

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
  const entries = useMemo(() => {
    const now = Date.now()
    const list = Object.values(artifacts).map(a => {
      const mins = Math.floor((now - a.modifiedAt) / 60000)
      return {
        filename: a.path.split('/').pop() || a.path,
        modifiedAgo: mins < 1 ? 'just now' : mins < 60 ? `modified ${mins}m ago` : `modified ${Math.floor(mins / 60)}h ago`,
        variant: mins < 5 ? ('recent' as const) : ('stable' as const),
        _ts: a.modifiedAt,
      }
    })
    list.sort((a, b) => b._ts - a._ts)
    return list.map(({ filename, modifiedAgo, variant }) => ({ filename, modifiedAgo, variant }))
  }, [artifacts])
  return <ArtifactsSidebarOrg artifacts={entries} />
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
      currentStep: a.stepName || (a.step > 0 ? `step ${a.step}` : 'step 0'),
    }))
  }, [agents])
  return <ScoutBar scouts={scouts} />
}

// ---------------------------------------------------------------------------
// Content stream
// ---------------------------------------------------------------------------

function renderEntry(entry: ConversationEntry, i: number) {
  switch (entry.type) {
    case 'thinking':
      return <ThinkingBlock key={i}><Md>{entry.content}</Md></ThinkingBlock>
    case 'text':
      return <ProseCard key={i}><Md>{entry.text}</Md></ProseCard>
    case 'tool_read':
      return <ToolCallRow key={i} tool="read" command={entry.lines ? `${entry.file}:${entry.lines}` : entry.file} status={entry.inFlight ? 'running' : 'done'} />
    case 'tool_write':
      return <ToolCallRow key={i} tool="write" command={entry.file} status={entry.inFlight ? 'running' : 'done'} />
    case 'tool_edit':
      return <ToolCallRow key={i} tool="edit" command={entry.file} status={entry.inFlight ? 'running' : 'done'} />
    case 'tool_bash':
      return <ToolCallRow key={i} tool="bash" command={entry.command} status={entry.inFlight ? 'running' : 'done'} />
    case 'tool_grep':
      return <ToolCallRow key={i} tool="grep" command={entry.pattern} status={entry.inFlight ? 'running' : 'done'} />
    case 'tool_ls':
      return <ToolCallRow key={i} tool="ls" command={entry.path} status={entry.inFlight ? 'running' : 'done'} />
    case 'tool_generic':
      return <ToolCallRow key={i} tool={entry.toolName} command={entry.summary} status={entry.inFlight ? 'running' : 'done'} />
    case 'step':
      return <StepHeader key={i} stepNumber={entry.step} totalSteps={entry.totalSteps ?? 0} stepName={entry.stepName} />
    case 'debug_step_guidance':
      return <StepGuidancePill key={i} status="active" defaultExpanded={false}><Md>{entry.content}</Md></StepGuidancePill>
    case 'user_message': {
      const ts = new Date(entry.timestampMs).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      return <UserBubble key={i} timestamp={ts}><Md>{entry.content}</Md></UserBubble>
    }
    case 'phase_boundary':
      return <PhaseBoundary key={i} label={entry.message} />
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
  useAutoScroll(scrollRef)
  const hasEntries = !!(conversation?.entries?.length)
  const isWaiting = !hasEntries && !conversation?.isThinking && !conversation?.pendingText
  const hasInteraction = focus && focus.type !== 'conversation'
  const showFeedback = run !== null && !hasInteraction
  return (
    <div className="content-column" ref={scrollRef}>
      <div className="content-stream">
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
            <FeedbackInput onSend={msg => api.sendChatMessage(msg)} disabled={!!run?.completion} />
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

export default function App() {
  const run = useStore(s => s.run)
  const connected = useStore(s => s.connected)
  const settingsOpen = useStore(s => s.settingsOpen)
  const header = useHeaderData()

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

  const openSettings = () => useStore.getState().setSettingsOpen(true)
  const focus = run?.focus
  const hasInteraction = focus && focus.type !== 'conversation'
  const completion = run?.completion

  if (!connected) {
    return (
      <div className="app-root">
        <HeaderBar phase="" step="" totalSteps={0} currentStep={0} onSettingsClick={openSettings} />
        <div className="single-column"><div className="loading-center">connecting…</div></div>
      </div>
    )
  }

  if (!run) {
    return (
      <div className="app-root">
        <HeaderBar phase="" step="" totalSteps={0} currentStep={0} onSettingsClick={openSettings} />
        <div className="single-column"><NewRunForm /></div>
        <Notification />{settingsOpen && <SettingsOverlay />}
      </div>
    )
  }

  if (hasInteraction) {
    return (
      <div className="app-root">
        <HeaderBar {...header} onSettingsClick={openSettings} />
        <div className="workflow-grid">
          <div className="content-column"><ElicitationView /></div>
          <ConnectedSidebar />
        </div>
        <Notification />{settingsOpen && <SettingsOverlay />}
      </div>
    )
  }

  if (completion) {
    return (
      <div className="app-root">
        <HeaderBar {...header} onSettingsClick={openSettings} />
        <div className="workflow-grid"><CompletionView /><ConnectedSidebar /></div>
        <Notification />{settingsOpen && <SettingsOverlay />}
      </div>
    )
  }

  return (
    <div className="app-root">
      <HeaderBar {...header} onSettingsClick={openSettings} />
      <div className="workflow-grid"><ContentStream /><ConnectedSidebar /></div>
      <ConnectedScoutBar />
      <Notification />{settingsOpen && <SettingsOverlay />}
    </div>
  )
}
