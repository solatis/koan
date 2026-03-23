// Root layout component. Everything lives inside a single centred max-width
// container (.app). The header is a normal flex child (not position:fixed);
// it stays at the top because .app is a flex column with overflow:hidden and
// child areas scroll internally.
//
// Three-column workspace shell below the header:
//
//   Left   -- StatusSidebar (live mode only)
//   Center -- main-panel: PhaseContent (interactive) or ActivityFeed + StreamingOutput (live)
//   Right  -- ArtifactsFolder (always mounted)
//
// isInteractive = !phase || pendingInput || showSettings || phase === 'completed'
//
// AgentMonitor and Notifications are always mounted; they manage their own
// visibility via internal selectors.

import { Header } from './Header.jsx'
import { PhaseContent } from './PhaseContent.jsx'
import { ActivityFeed } from './ActivityFeed.jsx'
import { AgentMonitor } from './AgentMonitor.jsx'
import { StatusSidebar } from './StatusSidebar.jsx'
import { Notifications } from './Notifications.jsx'
// StreamingOutput removed — streaming tokens now render inline in ActivityFeed's ThinkingCard
import { ArtifactsFolder } from './ArtifactsFolder.jsx'
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
      <Header />
      <div class="workspace">
        {!isInteractive && <StatusSidebar />}
        <div class="workspace-main">
          <main class="main-panel">
            {isInteractive ? (
              <div class="phase-content">
                <PhaseContent token={token} topic={topic} />
              </div>
            ) : (
              <ActivityFeed />
            )}
          </main>
        </div>
        <ArtifactsFolder token={token} />
      </div>
      <AgentMonitor />
      <Notifications />
    </div>
  )
}
