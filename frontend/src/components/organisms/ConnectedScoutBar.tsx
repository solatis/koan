/**
 * ConnectedScoutBar -- store connector for the sub-agent status bar.
 *
 * Reads the agents map via selectAgents (narrow selector; re-renders only when
 * agents change). The elapsed time derivation is in-component because it uses
 * Date.now() and cannot be captured in a pure reselect selector without
 * continuous re-rendering.
 *
 * M6: passes role to ScoutRow so reviewer and executor agents render with a
 * role-appropriate label badge alongside scouts. The bar lists all non-primary
 * agents regardless of role.
 *
 * Moved from App.tsx to this module in M5.
 */

import { useMemo } from 'react'
import { useStore } from '../../store/index'
import { selectAgents } from '../../store/selectors'
import { formatElapsed } from '../../hooks/useElapsed'
import { ScoutBar } from './ScoutBar'

export function ConnectedScoutBar() {
  const agents = useStore(selectAgents)

  const scouts = useMemo(() => {
    const now = Date.now()
    return Object.values(agents).filter(a => !a.isPrimary).map(a => ({
      name: a.label || a.role,
      // role is forwarded so ScoutRow can display a role badge
      // (scout / executor / reviewer) alongside the agent name.
      role: a.role as string,
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
