import { useMemo } from 'react'
import { useStore, AgentInfo } from '../store/index'
import { useElapsed } from '../hooks/useElapsed'
import { formatTokens } from '../utils'

function AgentRow({ agent }: { agent: AgentInfo }) {
  const elapsed = useElapsed(agent.startedAt)
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
      <span className="agent-row-tokens">{formatTokens(agent.tokensSent, agent.tokensReceived)}</span>
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
  const scouts = useStore(s => s.scouts)
  const completedAgents = useStore(s => s.completedAgents)
  const queuedScouts = useStore(s => s.queuedScouts)

  const { running, done, failed } = useMemo(() => {
    const runList = Object.values(scouts)
    const doneList = completedAgents.filter(a => a.status === 'done' && a.role === 'scout')
    const failList = completedAgents.filter(a => a.status === 'failed' && a.role === 'scout')
    return { running: runList, done: doneList, failed: failList }
  }, [scouts, completedAgents])

  const total = running.length + done.length + failed.length + queuedScouts.length
  if (total === 0) return null

  // Collapse to just the counter bar when nothing is active
  const hasActive = running.length > 0 || queuedScouts.length > 0
  const collapsed = !hasActive

  return (
    <div id="monitor" className="monitor">
      <div className="monitor-inner">
        <CounterBar
          running={running.length}
          queued={queuedScouts.length}
          done={done.length}
          failed={failed.length}
        />

        {!collapsed && (
          <>
            {running.length > 0 && (
              <>
                <SectionHeader icon="●" label="running" className="section-running" />
                {running.map(a => <AgentRow key={a.agentId} agent={a} />)}
              </>
            )}

            {queuedScouts.length > 0 && (
              <>
                <SectionHeader icon="○" label="queued" className="section-queued" />
                {queuedScouts.map((q, i) => (
                  <div key={i} className="agent-row agent-row-queued">
                    <span className="agent-row-icon agent-status-queued">○</span>
                    <span className="agent-row-name agent-name-queued">{q.label || 'scout'}</span>
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
          </>
        )}
      </div>
    </div>
  )
}
