import { ProgressBar } from './ProgressBar.jsx'
import { Header } from './Header.jsx'
import { SubagentMeta } from './SubagentMeta.jsx'
import { PhaseContent } from './PhaseContent.jsx'
import { ActivityFeed } from './ActivityFeed.jsx'
import { AgentMonitor } from './AgentMonitor.jsx'
import { Notifications } from './Notifications.jsx'
import { useStore } from '../store.js'

export function App({ token, topic }) {
  const phase = useStore(s => s.phase)
  const pending = useStore(s => s.pendingInput)
  const showSettings = useStore(s => s.showSettings)

  // When showing interactive content (forms, model config, loading, completion), use scroll layout
  // When showing live subagent activity, use fill layout with activity feed
  const isInteractive = !phase || pending || showSettings || phase === 'completed'

  return (
    <div class="app">
      <ProgressBar />
      <Header />
      {isInteractive ? (
        <main class="main-panel">
          <div class="phase-content">
            <PhaseContent token={token} topic={topic} />
          </div>
        </main>
      ) : (
        <main class="main-panel">
          <SubagentMeta />
          <ActivityFeed />
        </main>
      )}
      <AgentMonitor />
      <Notifications />
    </div>
  )
}
