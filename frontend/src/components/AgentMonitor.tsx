import { useMemo } from 'react'
import { useStore, Agent } from '../store/index'
import { useElapsed } from '../hooks/useElapsed'
import { formatTokens } from '../utils'

function AgentRow({ agent }: { agent: Agent }) {
  const elapsed = useElapsed(agent.startedAtMs)
  const status = agent.status

  const statusIcon = status === 'running' ? '›'
    : status === 'done' ? '✓'
    : '✘'
  const statusCls = `agent-status-${status}`
  const nameCls = `agent-name-${status}`
  const doingCls = status === 'failed' ? 'agent-doing-failed' : 'agent-doing-dim'
  const doingText = status === 'failed'
    ? (agent.error || 'failed')
    : status === 'done'
    ? 'done'
    : (agent.lastTool || agent.stepName || `step ${agent.step}`)

  return (
    <div className={`agent-row agent-row-${status}`}>
      <span className={`agent-row-icon ${statusCls}`}>{statusIcon}</span>
      <span className={`agent-row-name ${nameCls}`}>{agent.label || agent.role}</span>
      <span className="agent-row-model">{agent.model ?? '--'}</span>
      <span className="agent-row-tokens">
        {formatTokens(agent.conversation.inputTokens, agent.conversation.outputTokens)}
      </span>
      <span className="agent-row-time">{elapsed}</span>
      <span className={`agent-row-doing ${doingCls}`}>{doingText}</span>
    </div>
  )
}

function CounterBar({ running, queued, done, failed }: {
  running: number; queued: number; done: number; failed: number
}) {
  return (
    <div className="agent-counter-bar">
      <div className="agent-counter agent-counter-running">
        <span className="agent-counter-num">{running}</span>
        <span className="agent-counter-label">running</span>
      </div>
      <div className="agent-counter agent-counter-queued">
        <span className="agent-counter-num">{queued}</span>
        <span className="agent-counter-label">queued</span>
      </div>
      <div className="agent-counter agent-counter-done">
        <span className="agent-counter-num">{done}</span>
        <span className="agent-counter-label">done</span>
      </div>
      <div className="agent-counter agent-counter-failed">
        <span className="agent-counter-num">{failed}</span>
        <span className="agent-counter-label">failed</span>
      </div>
    </div>
  )
}

function SectionHeader({ icon, label, className }: {
  icon: string; label: string; className: string
}) {
  return (
    <div className={`agent-section-header ${className}`}>
      {icon} {label}
    </div>
  )
}

export function AgentMonitor() {
  const agents = useStore(s => s.run?.agents ?? {})

  const { running, queued, done, failed } = useMemo(() => {
    const all = Object.values(agents)
    return {
      running: all.filter(a => !a.isPrimary && a.status === 'running'),
      queued:  all.filter(a => a.status === 'queued'),
      done:    all.filter(a => a.status === 'done' && !a.isPrimary),
      failed:  all.filter(a => a.status === 'failed' && !a.isPrimary),
    }
  }, [agents])

  const total = running.length + queued.length + done.length + failed.length
  if (total === 0) return null

  // Hide entirely when nothing is active — counter bar adds no value
  // when all agents are done.
  const hasActive = running.length > 0 || queued.length > 0
  if (!hasActive) return null

  return (
    <div id="monitor" className="monitor">
      <div className="monitor-inner">
        <CounterBar
          running={running.length}
          queued={queued.length}
          done={done.length}
          failed={failed.length}
        />

        {running.length > 0 && (
          <>
            <SectionHeader icon="●" label="running" className="section-running" />
            {running.map(a => <AgentRow key={a.agentId} agent={a} />)}
          </>
        )}

        {queued.length > 0 && (
          <>
            <SectionHeader icon="○" label="queued" className="section-queued" />
            {queued.map(a => (
              <div key={a.agentId} className="agent-row agent-row-queued">
                <span className="agent-row-icon agent-status-queued">○</span>
                <span className="agent-row-name agent-name-queued">{a.label || 'scout'}</span>
                <span className="agent-row-model">--</span>
                <span className="agent-row-tokens">--</span>
                <span className="agent-row-time">--</span>
                <span className="agent-row-doing agent-doing-dim">queued</span>
              </div>
            ))}
          </>
        )}

        {done.length > 0 && (
          <>
            <SectionHeader icon="✓" label="done" className="section-done" />
            {done.map(a => <AgentRow key={a.agentId} agent={a} />)}
          </>
        )}

        {failed.length > 0 && (
          <>
            <SectionHeader icon="✘" label="failed" className="section-failed" />
            {failed.map(a => <AgentRow key={a.agentId} agent={a} />)}
          </>
        )}
      </div>
    </div>
  )
}
