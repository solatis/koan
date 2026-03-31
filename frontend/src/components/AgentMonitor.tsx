import { useMemo } from 'react'
import { useStore, AgentInfo } from '../store/index'
import { useElapsed } from '../hooks/useElapsed'
import { formatTokens } from '../utils'

function AgentRow({ agent }: { agent: AgentInfo }) {
  const elapsed = useElapsed(agent.startedAt)
  const status = agent.status

  const statusIcon = status === 'running' ? '›'
    : status === 'done' ? '✓'
    : status === 'failed' ? '✘'
    : '○'
  const statusCls = `agent-status-${status}`
  const nameCls = `agent-name-${status}`
  const doingCls = status === 'failed' ? 'agent-doing-failed' : 'agent-doing-dim'
  const doingText = status === 'failed'
    ? (agent.error || 'failed')
    : status === 'done'
    ? 'done'
    : (agent.stepName || `step ${agent.step}`)

  return (
    <div className={`agent-row agent-row-${status}`}>
      <span className={`agent-row-icon ${statusCls}`}>{statusIcon}</span>
      <span className={`agent-row-name ${nameCls}`}>{agent.role}</span>
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

  const { running, done, failed } = useMemo(() => {
    const runList = Object.values(scouts)
    const doneList = completedAgents.filter(a => a.status === 'done')
    const failList = completedAgents.filter(a => a.status === 'failed')
    return { running: runList, done: doneList, failed: failList }
  }, [scouts, completedAgents])

  const total = running.length + done.length + failed.length
  if (total === 0) return null

  return (
    <div id="monitor" className="monitor">
      <div className="monitor-inner">
        <CounterBar
          running={running.length}
          queued={0}
          done={done.length}
          failed={failed.length}
        />

        {running.length > 0 && (
          <>
            <SectionHeader icon="●" label="running" className="section-running" />
            {running.map(a => <AgentRow key={a.agentId} agent={a} />)}
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
