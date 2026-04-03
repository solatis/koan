import { useEffect } from 'react'
import { useStore } from './store/index'
import { connectSSE } from './sse/connect'
import { Header } from './components/Header'
import { LandingPage } from './components/LandingPage'
import { StatusSidebar } from './components/StatusSidebar'
import { ActivityFeed } from './components/ActivityFeed'
import { AgentMonitor } from './components/AgentMonitor'
import { ArtifactsSidebar } from './components/ArtifactsSidebar'
import { Notification } from './components/Notification'
import { SettingsOverlay } from './components/SettingsOverlay'
import { Completion } from './components/Completion'
import { AskWizard } from './components/interactions/AskWizard'
import { ArtifactReview } from './components/interactions/ArtifactReview'

function InteractionView() {
  const focus = useStore(s => s.run?.focus)
  if (!focus) return null
  if (focus.type === 'question') return <AskWizard />
  if (focus.type === 'review') return <ArtifactReview />
  return null
}

function WorkspaceMain() {
  const focus = useStore(s => s.run?.focus)
  const completion = useStore(s => s.run?.completion)

  const hasInteraction = focus && focus.type !== 'conversation'

  return (
    <div className="workspace-main">
      {hasInteraction ? (
        <InteractionView />
      ) : completion ? (
        <Completion />
      ) : (
        <ActivityFeed />
      )}
      <AgentMonitor />
    </div>
  )
}

export default function App() {
  const run = useStore(s => s.run)
  const settingsOpen = useStore(s => s.settingsOpen)

  useEffect(() => {
    let es: EventSource | null = null
    let retryDelay = 500

    function connect() {
      es = connectSSE(useStore)
      // Override the onerror set inside connectSSE to schedule our retry.
      es.onerror = () => {
        useStore.getState().setConnected(false)
        es?.close()
        // Exponential backoff capped at 5s.
        setTimeout(connect, retryDelay)
        retryDelay = Math.min(retryDelay * 2, 5000)
      }
      // Reset backoff on successful connection.
      es.onopen = () => {
        retryDelay = 500
      }
    }

    connect()

    // Cleanup on unmount — prevents duplicate SSE connections in React StrictMode.
    return () => {
      es?.close()
    }
  }, []) // Empty dep array: connect once; reconnect is managed inside

  const connected = useStore(s => s.connected)

  // Show a minimal loading state until the first SSE snapshot arrives.
  // This prevents a blank cornsilk void while the server is initializing.
  if (!connected) {
    return (
      <div className="app">
        <Header />
        <div className="loading-state">
          <span className="loading-label">connecting…</span>
        </div>
      </div>
    )
  }

  return (
    <div className="app">
      <Header />

      {!run ? (
        <LandingPage />
      ) : (
        <div className="workspace">
          <StatusSidebar />
          <WorkspaceMain />
          <ArtifactsSidebar />
        </div>
      )}

      <Notification />
      {settingsOpen && <SettingsOverlay />}
    </div>
  )
}
