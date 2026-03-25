import { useRef, useEffect, useState, useCallback } from 'preact/hooks'
import { marked } from 'marked'
import { useStore } from '../store.js'

function ThinkingTimer({ since }) {
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    const start = new Date(since).getTime()
    const tick = () => setElapsed(Math.floor((Date.now() - start) / 1000))
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [since])

  const text = elapsed < 60
    ? `${elapsed}s`
    : `${Math.floor(elapsed / 60)}m ${elapsed % 60}s`

  return <span class="thinking-timer">{text}</span>
}

/** Card for thinking entries — shows expandable thought content */
function ThinkingCard({ line, isInFlight, isFlashing, dimmed }) {
  const [expanded, setExpanded] = useState(false)
  const bodyRef = useRef(null)
  const [isClamped, setIsClamped] = useState(false)

  // Detect whether the body text is actually clamped (more content than visible)
  useEffect(() => {
    const el = bodyRef.current
    if (el) setIsClamped(el.scrollHeight > el.clientHeight + 2)
  }, [line.body, expanded])

  // While in-flight with streaming body, treat as always expanded so the
  // user sees tokens appear. Clamping only applies to completed thoughts.
  const isStreaming = isInFlight && !!line.body
  const showExpanded = expanded || isStreaming

  const cls = [
    'activity-card',
    'activity-card-thinking',
    isInFlight  ? 'activity-card-active' : '',
    isFlashing  ? 'activity-flash' : '',
    dimmed      ? 'activity-frozen' : '',
  ].filter(Boolean).join(' ')

  return (
    <div class={cls}>
      <div class="activity-card-header">
        <span class={`activity-card-tool${isInFlight ? ' thinking-dot' : ''}`}>thinking</span>
        <span class="activity-card-meta">
          {isInFlight
            ? <ThinkingTimer since={line.ts} />
            : line.summary
          }
        </span>
      </div>
      {line.body && (
        <>
          <div
            ref={bodyRef}
            class={`activity-card-body${showExpanded ? ' expanded' : ''}`}
          >
            {line.body}{isStreaming && <span class="streaming-cursor" />}
          </div>
          {(!isStreaming && isClamped && !expanded) && (
            <div class="activity-card-more" onClick={() => setExpanded(true)}>
              show more ▸
            </div>
          )}
          {(!isStreaming && expanded) && (
            <div class="activity-card-more" onClick={() => setExpanded(false)}>
              show less ▴
            </div>
          )}
        </>
      )}
    </div>
  )
}

function formatElapsedShort(ms) {
  const sec = Math.floor(ms / 1000)
  if (sec < 60) return `${sec}s`
  const min = Math.floor(sec / 60)
  const rem = sec % 60
  return rem > 0 ? `${min}m ${rem}s` : `${min}m`
}

/** Card for koan_request_scouts — shows dispatched scouts with name + role.
 *  Cross-references live scout status from the store to color the accent bar.
 *  Shows total elapsed time once all scouts have completed. */
function ScoutCard({ line, isInFlight, isFlashing, dimmed }) {
  const scoutDefs = line.scouts || []
  const liveScouts = useStore(s => s.scouts)
  const allAgents = useStore(s => s.agents)

  // Build id→status lookup from live scout data
  const statusById = {}
  for (const s of liveScouts) statusById[s.id] = s.status

  // Compute total elapsed from scout agent timing data
  const scoutIds = new Set(scoutDefs.map(s => s.id))
  const scoutAgents = allAgents.filter(a => scoutIds.has(a.name || a.id))
  const allDone = scoutAgents.length > 0 && scoutAgents.every(a => a.status === 'completed' || a.status === 'failed')
  let totalElapsed = null
  if (allDone) {
    const starts = scoutAgents.filter(a => a.startedAt).map(a => a.startedAt)
    const ends = scoutAgents.filter(a => a.completedAt).map(a => a.completedAt)
    if (starts.length > 0 && ends.length > 0) {
      totalElapsed = formatElapsedShort(Math.max(...ends) - Math.min(...starts))
    }
  }

  const cls = [
    'activity-card',
    'activity-card-scouts',
    isInFlight  ? 'activity-card-active' : '',
    isFlashing  ? 'activity-flash' : '',
    dimmed      ? 'activity-frozen' : '',
  ].filter(Boolean).join(' ')

  return (
    <div class={cls}>
      <div class="activity-card-header">
        <span class="activity-card-tool">
          dispatching {scoutDefs.length} scout{scoutDefs.length !== 1 ? 's' : ''}
        </span>
        <span class="activity-card-meta">
          {isInFlight
            ? <span class="activity-dots">…</span>
            : totalElapsed && <span class="activity-elapsed">{totalElapsed}</span>
          }
        </span>
      </div>
      <div class="scout-list">
        {scoutDefs.map((s, i) => {
          const status = statusById[s.id] ?? null
          const statusCls = status === 'running'   ? 'scout-running'
                          : status === 'completed' ? 'scout-completed'
                          : status === 'failed'    ? 'scout-failed'
                          :                          'scout-queued'
          return (
            <div key={i} class={`scout-entry ${statusCls}`}>
              <span class="scout-name">{s.id}</span>
              <span class="scout-role">{s.role}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

/** Standard line for tool calls and lifecycle events */
function ActivityLine({ line, isInFlight, isFlashing, dimmed }) {
  const cls = [
    'activity-line',
    line.highValue ? 'activity-high' : '',
    isInFlight     ? 'activity-inflight' : '',
    isFlashing     ? 'activity-flash' : '',
    dimmed         ? 'activity-frozen' : '',
  ].filter(Boolean).join(' ')

  return (
    <>
      <div class={cls}>
        <span class="activity-tool">{line.tool}</span>
        <span class="activity-summary">
          {line.summary || ''}
          {isInFlight && <span class="activity-dots">...</span>}
        </span>
      </div>
      {line.details?.map((d, j) => (
        <div key={j} class={`activity-line activity-detail${isInFlight ? ' activity-inflight' : ''}${dimmed ? ' activity-frozen' : ''}`}>
          <span class="activity-tool" />
          <span class="activity-summary">{d}</span>
        </div>
      ))}
    </>
  )
}

/** Render a single log line — used for both live and frozen zones */
function renderLine(line, isInFlight, isFlashing, key, dimmed = false, streamingText = '') {
  if (line.tool === 'thinking') {
    const thinkingLine = (isInFlight && streamingText)
      ? { ...line, body: streamingText.replace(/\n{3,}/g, '\n\n') }
      : line
    return (
      <ThinkingCard
        key={key}
        line={thinkingLine}
        isInFlight={isInFlight}
        isFlashing={isFlashing}
        dimmed={dimmed}
      />
    )
  }

  if (line.scouts) {
    return (
      <ScoutCard
        key={key}
        line={line}
        isInFlight={isInFlight}
        isFlashing={isFlashing}
        dimmed={dimmed}
      />
    )
  }

  return (
    <ActivityLine
      key={key}
      line={line}
      isInFlight={isInFlight}
      isFlashing={isFlashing}
      dimmed={dimmed}
    />
  )
}

// ---------------------------------------------------------------------------
// WorkflowChat: multi-turn conversation with the workflow orchestrator
// ---------------------------------------------------------------------------

function WorkflowChat({ turns, token }) {
  const [input, setInput] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [selectedPhase, setSelectedPhase] = useState(null)

  const lastTurn = turns[turns.length - 1]
  const awaitingUser = lastTurn?.role === 'orchestrator'

  function selectPhase(phase) {
    // Pre-fill rather than auto-submit. Lets the user add context before
    // sending: "Proceed with core-flows, but focus on auth requirements"
    setSelectedPhase(phase.phase)
    setInput(`Proceed with ${phase.label}`)
  }

  async function submit() {
    if (submitting || !input.trim() || !awaitingUser) return
    setSubmitting(true)

    const userText = input.trim()
    // Append user turn immediately for responsive feedback.
    useStore.setState(s => ({
      workflowChat: [...s.workflowChat, { role: 'user', text: userText, pending: true }]
    }))
    setInput('')
    setSelectedPhase(null)

    try {
      await fetch('/api/workflow-decision', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          token,
          requestId: lastTurn.requestId,
          feedback: userText,
        }),
      })
      // Clear the workflow chat — the decision has been submitted and the
      // orchestrator will proceed. The next phase event (or a new
      // workflow-decision event) will re-populate if needed.
      useStore.setState({ workflowChat: [] })
    } catch (err) {
      // Mark turn as failed so user can retry. Without this, the pipeline
      // hangs at pollIpcUntilResponse() indefinitely.
      useStore.setState(s => ({
        workflowChat: s.workflowChat.map(t =>
          t.role === 'user' && t.pending ? { ...t, pending: false, failed: true } : t
        )
      }))
    } finally {
      setSubmitting(false)
    }
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      submit()
    }
  }

  return (
    <div class="workflow-chat">
      {turns.map((turn, i) => (
        turn.role === 'orchestrator'
          ? <OrchestratorTurn key={i} turn={turn} onSelect={selectPhase}
                              isLatest={i === turns.length - 1}
                              selectedPhase={selectedPhase} />
          : <UserTurn key={i} turn={turn} onRetry={(text) => { setInput(text) }} />
      ))}

      {awaitingUser && (
        <div class="workflow-chat-input">
          <textarea
            class="workflow-feedback"
            placeholder="Type instructions or feedback, or click an option above…"
            value={input}
            onInput={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={submitting}
            rows={3}
          />
          <div class="form-actions">
            <button class="btn btn-primary" onClick={submit}
                    disabled={submitting || !input.trim()}>
              Continue →
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function OrchestratorTurn({ turn, onSelect, isLatest, selectedPhase }) {
  const renderedHtml = marked.parse(turn.statusReport)
  return (
    <div class="workflow-turn workflow-turn-orchestrator">
      <div class="workflow-turn-header">
        <span class="workflow-turn-role">workflow orchestrator</span>
      </div>
      <div class="workflow-turn-body"
           dangerouslySetInnerHTML={{ __html: renderedHtml }} />
      {/* Only show phase options on the latest orchestrator turn */}
      {isLatest && (
        <div class="workflow-options">
          {turn.recommendedPhases.map((p, i) => {
            const isSelected = selectedPhase === p.phase
            return (
              <button key={i}
                      class={`workflow-option${p.recommended && !selectedPhase ? ' recommended' : ''}${isSelected ? ' selected' : ''}`}
                      onClick={() => onSelect(p)}>
                <span class="workflow-option-label">{p.label || p.phase}</span>
                <span class="workflow-option-context">{p.context}</span>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}

function UserTurn({ turn, onRetry }) {
  return (
    <div class={`workflow-turn workflow-turn-user${turn.failed ? ' workflow-turn-failed' : ''}`}>
      <span class="workflow-turn-body">{turn.text}</span>
      {turn.pending && <span class="workflow-turn-status">Sending…</span>}
      {turn.failed && (
        <div class="workflow-turn-error">
          <span>Failed to send.</span>
          <button class="btn btn-sm" onClick={() => onRetry(turn.text)}>Retry</button>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// ActivityFeed: four-zone layout
// ---------------------------------------------------------------------------

export function ActivityFeed({ token }) {
  const logs        = useStore(s => s.logs)
  const frozenLogs  = useStore(s => s.frozenLogs)
  const workflowChat = useStore(s => s.workflowChat)
  const streamingText = useStore(s => s.streamingText)
  const containerRef = useRef(null)
  const stickRef = useRef(true)

  // Track previous last-line to detect in-flight → completed transitions.
  const prevLastRef = useRef(null)
  const [flashIndex, setFlashIndex] = useState(-1)

  // Auto-scroll to bottom when new logs arrive or streaming text grows,
  // but only if already at bottom.
  useEffect(() => {
    const el = containerRef.current
    if (el && stickRef.current) {
      el.scrollTop = el.scrollHeight
    }
  }, [logs, streamingText, frozenLogs, workflowChat])

  // Detect when the last line transitions from in-flight to completed and flash it.
  useEffect(() => {
    const lastLine = logs[logs.length - 1]
    if (prevLastRef.current?.inFlight && lastLine && !lastLine.inFlight) {
      const idx = logs.length - 1
      setFlashIndex(idx)
      setTimeout(() => setFlashIndex(-1), 400)
    }
    prevLastRef.current = lastLine ? { ...lastLine } : null
  }, [logs])

  const onScroll = useCallback(() => {
    const el = containerRef.current
    if (!el) return
    stickRef.current = el.scrollTop + el.clientHeight >= el.scrollHeight - 30
  }, [])

  const hasOrchestratorSession = frozenLogs.length > 0

  if (!hasOrchestratorSession && logs.length === 0 && workflowChat.length === 0) return null

  return (
    <div class="activity-feed-scroll" ref={containerRef} onScroll={onScroll}>
      <div class="activity-feed-inner">

        {/* Zone 1: frozen phase activity — rendered identically to live activity */}
        {hasOrchestratorSession && frozenLogs.map((line, i) =>
          renderLine(line, false, false, `frozen-${i}`, false, '')
        )}

        {/* Zone 2: orchestrator session separator */}
        {hasOrchestratorSession && (
          <div class="workflow-separator">
            <span class="workflow-separator-label">Evaluating workflow…</span>
          </div>
        )}

        {/* Zone 3: live orchestrator tool calls */}
        {logs.map((line, i) => {
          const isInFlight = !!line.inFlight && i === logs.length - 1
          const isFlashing = i === flashIndex
          return renderLine(line, isInFlight, isFlashing, `live-${i}`, false, isInFlight ? streamingText : '')
        })}

        {/* Zone 4: WorkflowChat thread */}
        {workflowChat.length > 0 && (
          <WorkflowChat turns={workflowChat} token={token} />
        )}

      </div>
    </div>
  )
}
