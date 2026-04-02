import { useRef, useState } from 'react'
import { useStore, ConversationEntry } from '../store/index'
import { useAutoScroll } from '../hooks/useAutoScroll'
import { Md } from './Md'

// -- Thinking ------------------------------------------------------------------

function ThinkingCard({ content }: { content: string }) {
  const [expanded, setExpanded] = useState(false)
  const isLong = content.length > 300

  return (
    <div className="activity-card activity-card-thinking">
      <div className="activity-card-header">
        <span className="activity-card-tool">thinking</span>
      </div>
      {content && (
        <div className={`activity-card-body ${expanded ? 'expanded' : ''}`}>
          <Md>{content}</Md>
        </div>
      )}
      {isLong && !expanded && (
        <div className="activity-card-more" onClick={() => setExpanded(true)}>
          show more
        </div>
      )}
    </div>
  )
}

// -- Step header ---------------------------------------------------------------

function StepHeader({ step, stepName, totalSteps }: {
  step: number; stepName: string; totalSteps: number | null
}) {
  const label = totalSteps ? `step ${step}/${totalSteps}` : `step ${step}`
  return (
    <div className="step-header">
      <span className="step-header-label">{label}</span>
      {stepName && <span className="step-header-name">{stepName}</span>}
    </div>
  )
}

// -- Text block ----------------------------------------------------------------

function TextBlock({ text }: { text: string }) {
  return <div className="stream-output"><Md>{text}</Md></div>
}

// -- Debug step guidance -------------------------------------------------------

function DebugGuidanceCard({ content }: { content: string }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="activity-card activity-card-debug">
      <div className="activity-card-header" onClick={() => setExpanded(!expanded)} style={{ cursor: 'pointer' }}>
        <span className="activity-card-tool">step guidance</span>
        <span className="activity-card-toggle">{expanded ? '▾' : '▸'}</span>
      </div>
      {expanded && (
        <div className="activity-card-body expanded">
          <Md>{content}</Md>
        </div>
      )}
    </div>
  )
}

// -- Tool lines ----------------------------------------------------------------

function statusIcon(inFlight: boolean) { return inFlight ? '›' : '✓' }
function statusClass(inFlight: boolean) { return inFlight ? 'activity-inflight' : 'activity-done' }

function ToolLine({ tool, summary, inFlight }: { tool: string; summary: string; inFlight: boolean }) {
  return (
    <div className={`activity-line ${statusClass(inFlight)}`}>
      <span className="activity-status">{statusIcon(inFlight)}</span>
      <span className="activity-tool">{tool}</span>
      <span className="activity-summary">
        {summary}
        {inFlight && <span className="activity-dots">...</span>}
      </span>
    </div>
  )
}

function DetailLine({ tool, detail, inFlight }: { tool: string; detail: string; inFlight: boolean }) {
  return (
    <div className={`activity-line ${statusClass(inFlight)}`}>
      <span className="activity-status">{statusIcon(inFlight)}</span>
      <span className="activity-tool">{tool}</span>
      <span className="activity-detail">{detail}</span>
      {inFlight && <span className="activity-dots">...</span>}
    </div>
  )
}

// -- Entry renderer -----------------------------------------------------------

function renderEntry(entry: ConversationEntry, i: number) {
  switch (entry.type) {
    case 'thinking':
      return <ThinkingCard key={i} content={entry.content} />
    case 'step':
      return <StepHeader key={i} step={entry.step} stepName={entry.stepName} totalSteps={entry.totalSteps} />
    case 'text':
      return <TextBlock key={i} text={entry.text} />
    case 'tool_read': {
      const detail = entry.lines ? `${entry.file}:${entry.lines}` : entry.file
      return <DetailLine key={i} tool="read" detail={detail} inFlight={entry.inFlight} />
    }
    case 'tool_write':
      return <DetailLine key={i} tool="write" detail={entry.file} inFlight={entry.inFlight} />
    case 'tool_edit':
      return <DetailLine key={i} tool="edit" detail={entry.file} inFlight={entry.inFlight} />
    case 'tool_bash':
      return <DetailLine key={i} tool="bash" detail={entry.command} inFlight={entry.inFlight} />
    case 'tool_grep':
      return <DetailLine key={i} tool="grep" detail={entry.pattern} inFlight={entry.inFlight} />
    case 'tool_ls':
      return <DetailLine key={i} tool="ls" detail={entry.path} inFlight={entry.inFlight} />
    case 'tool_generic':
      return <ToolLine key={i} tool={entry.toolName} summary={entry.summary} inFlight={entry.inFlight} />
    case 'debug_step_guidance':
      return <DebugGuidanceCard key={i} content={entry.content} />
    default:
      return null
  }
}

// -- Feed ---------------------------------------------------------------------

export function ActivityFeed() {
  const focusAgentId = useStore(s => s.run?.focus?.agentId)
  const conversation = useStore(s =>
    focusAgentId ? s.run?.agents?.[focusAgentId]?.conversation : undefined
  )
  const scrollRef = useRef<HTMLDivElement>(null)
  useAutoScroll(scrollRef)

  return (
    <div className="activity-feed-scroll" ref={scrollRef}>
      <div id="activity-feed-inner" className="activity-feed-inner">
        {conversation?.entries.map(renderEntry)}

        {/* Active thinking card — shown while LLM is reasoning */}
        {conversation?.isThinking && conversation.pendingThinking && (
          <div className="activity-card activity-card-thinking activity-card-active">
            <div className="activity-card-header">
              <span className="activity-card-tool">thinking</span>
            </div>
            <div className="activity-card-body expanded">
              <Md>{conversation.pendingThinking}</Md>
            </div>
          </div>
        )}

        {/* Thinking indicator — no content yet */}
        {conversation?.isThinking && !conversation.pendingThinking && (
          <div className="activity-thinking-indicator">
            <span className="thinking-dot">●</span>
            <span>Thinking…</span>
          </div>
        )}

        {/* Active stream output — text being produced right now */}
        {conversation?.pendingText && (
          <div className="stream-output">
            <Md>{conversation.pendingText}</Md>
            <span className="streaming-cursor" />
          </div>
        )}
      </div>
    </div>
  )
}
