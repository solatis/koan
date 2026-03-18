import { useStore } from '../store.js'
import { shortenModel, formatTokens } from '../lib/utils.js'

export function SubagentMeta() {
  const sub = useStore(s => s.subagent)
  if (!sub) return null

  const stepLabel = sub.stepName || (sub.step && sub.totalSteps ? `Step ${sub.step}/${sub.totalSteps}` : null)

  return (
    <div class="subagent-meta">
      <span class="meta-role">{sub.role}</span>
      {sub.model && <span class="meta-item">{shortenModel(sub.model)}</span>}
      {stepLabel && <span class="meta-item">{stepLabel}</span>}
      {(sub.tokensSent > 0 || sub.tokensReceived > 0) && (
        <span class="meta-tokens">↑{formatTokens(sub.tokensSent || 0)} ↓{formatTokens(sub.tokensReceived || 0)}</span>
      )}
    </div>
  )
}
