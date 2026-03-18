import { shortenModel, formatTokens } from '../lib/utils.js'

export function AgentRow({ agent, maxLines = 5 }) {
  const actions = agent.recentActions || []
  const start = Math.max(0, actions.length - maxLines)

  return (
    <tr>
      <td class="col-status agent-status-running">●</td>
      <td class="agent-name-running">{agent.name || agent.id}</td>
      <td class="col-model agent-model-cell">{shortenModel(agent.model)}</td>
      <td class="col-tokens agent-tokens-cell">{formatTokens(agent.tokensSent || 0)}</td>
      <td class="col-tokens agent-tokens-cell">{formatTokens(agent.tokensReceived || 0)}</td>
      <td class="col-doing">
        {actions.length > 0 ? (
          <div class="agent-doing-lines">
            {actions.slice(start).map((action, i) => {
              // Gracefully handle both old string[] and new object[] formats.
              const text = typeof action === 'string'
                ? action
                : (action.summary ? `${action.tool}: ${action.summary}` : action.tool)
              const inFlight = typeof action === 'object' && !!action.inFlight

              return (
                <div key={i} class={`agent-doing-line${inFlight ? ' agent-doing-inflight' : ''}`}>
                  <span class={`agent-doing-prefix ${inFlight ? 'prefix-active' : 'prefix-done'}`}>
                    {inFlight ? '●' : '·'}
                  </span>
                  {text}
                </div>
              )
            })}
          </div>
        ) : (
          <span class="agent-doing-line">initializing...</span>
        )}
      </td>
    </tr>
  )
}
