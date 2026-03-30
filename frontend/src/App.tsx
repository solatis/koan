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
import { WorkflowDecision } from './components/interactions/WorkflowDecision'
import { ArtifactReview } from './components/interactions/ArtifactReview'

function InteractionView() {
  const interaction = useStore(s => s.activeInteraction)
  if (!interaction) return null
  if (interaction.type === 'ask') return <AskWizard />
  if (interaction.type === 'workflow-decision') return <WorkflowDecision />
  if (interaction.type === 'artifact-review') return <ArtifactReview />
  return null
}

function WorkspaceMain() {
  const interaction = useStore(s => s.activeInteraction)
  const completion = useStore(s => s.completion)

  return (
    <div className="workspace-main">
      {interaction ? (
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
  const runStarted = useStore(s => s.runStarted)
  const settingsOpen = useStore(s => s.settingsOpen)
  const fatalError = useStore(s => s.fatalError)

  useEffect(() => {
    let es: EventSource | null = null
    let retryDelay = 500

    function connect() {
      // Do not reconnect after a fatal_error (server restart / stale version).
      // User must reload the page.
      if (useStore.getState().fatalError) return

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

    // Cleanup on unmount -- prevents duplicate SSE connections in React StrictMode.
    return () => {
      es?.close()
    }
  }, []) // Empty dep array: connect once, reconnect is managed inside

  if (fatalError) {
    return (
      <div className="app">
        <Header />
        <div style={{ padding: '2rem', textAlign: 'center' }}>
          <p>Connection lost. The server restarted or the session expired.</p>
          <button onClick={() => window.location.reload()}>Reload page</button>
        </div>
      </div>
    )
  }

  return (
    <div className="app">
      <Header />

      {!runStarted ? (
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
