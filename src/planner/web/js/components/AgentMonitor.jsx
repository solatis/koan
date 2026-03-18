import { useStore } from '../store.js'
import { formatTokens } from '../lib/utils.js'
import { AgentRow } from './AgentRow.jsx'

export function AgentMonitor() {
  const allAgents = useStore(s => s.agents)
  // Only show nested subagents (those with a parent), and only running ones
  const agents = allAgents.filter(a => a.status === 'running' && a.parent)
  const sent = agents.reduce((s, a) => s + (a.tokensSent || 0), 0)
  const recv = agents.reduce((s, a) => s + (a.tokensReceived || 0), 0)

  if (agents.length === 0) return null

  // Dynamic lines-per-agent based on count
  const maxLines = agents.length <= 3 ? 5
    : agents.length <= 6 ? 3
    : agents.length <= 10 ? 2
    : 1

  return (
    <footer class="monitor">
      <div class="agent-table-header">
        <span class="monitor-label">Subagents</span>
        <div class="agent-badges">
          <span class="badge active">{agents.length}</span>
        </div>
        <span class="token-totals">
          {(sent > 0 || recv > 0) ? `↑${formatTokens(sent)} ↓${formatTokens(recv)}` : ''}
        </span>
      </div>
      <table class="agent-table">
        <thead>
          <tr>
            <th class="col-status"></th>
            <th class="col-agent">agent</th>
            <th class="col-model">model</th>
            <th class="col-tokens">↑ sent</th>
            <th class="col-tokens">↓ recv</th>
            <th class="col-doing">doing</th>
          </tr>
        </thead>
        <tbody>
          {agents.map(a => <AgentRow key={a.id} agent={a} maxLines={maxLines} />)}
        </tbody>
      </table>
    </footer>
  )
}
