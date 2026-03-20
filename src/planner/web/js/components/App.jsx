import { ProgressBar } from './ProgressBar.jsx'
import { Header } from './Header.jsx'
import { SubagentMeta } from './SubagentMeta.jsx'
import { PhaseContent } from './PhaseContent.jsx'
import { ActivityFeed } from './ActivityFeed.jsx'
import { AgentMonitor } from './AgentMonitor.jsx'
import { StatusSidebar } from './StatusSidebar.jsx'
import { Notifications } from './Notifications.jsx'
import { useStore } from '../store.js'

export function App({ token, topic }) {
  const phase = useStore(s => s.phase)
  const pending = useStore(s => s.pendingInput)
  const showSettings = useStore(s => s.showSettings)

  // Interactive mode: forms, settings overlay, loading screen, completion.
  // Live mode: active subagent activity feed with status sidebar.
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
        // Live layout: activity feed on the left, status sidebar on the right.
        // The sidebar spans the full height of the content area, independently scrollable.
        <div class="live-layout">
          <div class="live-main">
            <main class="main-panel">
              <SubagentMeta />
              <ActivityFeed />
            </main>
          </div>
          <StatusSidebar />
        </div>
      )}
      <AgentMonitor />
      <Notifications />
    </div>
  )
}
