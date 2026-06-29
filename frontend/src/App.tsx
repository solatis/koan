/**
 * App -- thin shell: SSE lifecycle, completion effects, URL routing, and the
 * top-level layout switch.
 *
 * All run-view connected wrappers (ConnectedSidebar, ConnectedScoutBar,
 * ElicitationView, CompletionView, ReviewView, ConnectedSettingsPage,
 * ConnectedNewRunForm) were moved to components/organisms/ in M5.
 * useHeaderData was moved to hooks/useHeaderData.ts in M5.
 */

import { useEffect, useMemo, useRef } from 'react'
import { useLocation, useNavigate } from 'react-router'
import { useStore, CompletionInfo } from './store/index'
// DEBUG: expose store to window for browser-agent introspection
;(window as unknown as { __store: typeof useStore }).__store = useStore
import { connectSSE } from './sse/connect'
import { useHeaderData } from './hooks/useHeaderData'
import { derivePhaseNodes } from './store/selectors'
import * as api from './api/client'

import { HeaderBar } from './components/organisms/HeaderBar'
// Content stream and its sub-components moved to organisms/ContentStream.tsx in M2.
import { ContentStream } from './components/organisms/ContentStream'
import { ConnectedSidebar } from './components/organisms/ConnectedSidebar'
import { ConnectedScoutBar } from './components/organisms/ConnectedScoutBar'
import { ElicitationView } from './components/organisms/ElicitationView'
import { CompletionView } from './components/organisms/CompletionView'
import { ReviewView } from './components/organisms/ReviewView'
import { ConnectedSettingsPage } from './components/organisms/ConnectedSettingsPage'
import { ConnectedNewRunForm } from './components/organisms/ConnectedNewRunForm'

import { Notification } from './components/Notification'
import { SessionsPage } from './components/organisms/SessionsPage'
import { MemoryRoutes } from './components/organisms/MemoryRoutes'
import { TimelineRail } from './components/organisms/TimelineRail'
// Curation takeover removed in M7: koan_memory_propose gate retired; curation
// writes memory directly via koan_memorize/koan_forget.

// ---------------------------------------------------------------------------
// Navigation items
// ---------------------------------------------------------------------------

const NAV_ITEMS = [
  { label: 'New run', key: 'new-run' },
  { label: 'Sessions', key: 'sessions' },
  { label: 'Memory', key: 'memory' },
  { label: 'Settings', key: 'settings' },
]

// Maps nav keys to URL paths for URL-driven navigation.
const PATH_BY_KEY: Record<string, string> = {
  'new-run': '/',
  sessions: '/sessions',
  memory: '/memory',
  settings: '/settings',
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

export default function App() {
  const run = useStore(s => s.run)
  const connected = useStore(s => s.connected)
  const reviewingArtifact = useStore(s => s.reviewingArtifact)
  const completion = run?.completion ?? null
  const header = useHeaderData()
  const location = useLocation()
  const navigate = useNavigate()

  // Timeline rail: phase nodes derived from the run, plus the viewing-phase
  // UI state. onPhaseClick only records viewingPhaseId for now -- phase-scoped
  // content switching is a later task.
  const viewingPhaseId = useStore(s => s.viewingPhaseId)
  const setViewingPhaseId = useStore(s => s.setViewingPhaseId)
  const phaseNodes = useMemo(() => (run ? derivePhaseNodes(run) : []), [run])

  // Derive the active nav key from the current URL path so browser back/forward
  // updates the nav highlight without local state.
  const page: 'new-run' | 'sessions' | 'memory' | 'settings' =
    location.pathname.startsWith('/memory') ? 'memory'
    : location.pathname === '/sessions' ? 'sessions'
    : location.pathname === '/settings' ? 'settings'
    : 'new-run'

  // Auto-open effect removed in M6 -- koan_artifact_propose (and the
  // activeArtifactReview field it drove) was deleted in M5. Artifacts are
  // now opened on demand by the user clicking them in the sidebar.

  // Snapshot run.completion into lastCompletion on the null->non-null rising
  // edge only. The ref guards against re-snapshotting on every re-render or
  // on future events that re-emit the same completion object.
  const prevCompletionRef = useRef<CompletionInfo | null>(null)
  useEffect(() => {
    const current = run?.completion ?? null
    if (prevCompletionRef.current === null && current !== null) {
      useStore.getState().setLastCompletion(current)
    }
    prevCompletionRef.current = current
  }, [run?.completion])

  // Success: auto-clear + navigate after 3 seconds so the user can read the
  // completion banner before the overview appears. The timer is cancelled if
  // the component unmounts or if completion changes (e.g. SSE reconnect).
  useEffect(() => {
    if (!completion || !completion.success) return
    const timer = setTimeout(async () => {
      await api.clearRun()
      navigate('/')
    }, 3000)
    return () => clearTimeout(timer)
  }, [completion, navigate])

  useEffect(() => {
    let es: EventSource | null = null
    let retryDelay = 500
    function connect() {
      es = connectSSE(useStore)
      es.onerror = () => {
        useStore.getState().setConnected(false)
        es?.close()
        setTimeout(connect, retryDelay)
        retryDelay = Math.min(retryDelay * 2, 5000)
      }
      es.onopen = () => { retryDelay = 500 }
    }
    connect()
    return () => { es?.close() }
  }, [])

  const goToSettings = () => navigate('/settings')
  const focus = run?.focus

  // Derive sub-page breadcrumbs from the current URL for memory routes.
  const memoryCrumbs = useMemo(() => {
    if (!location.pathname.startsWith('/memory')) return undefined
    const parts = location.pathname.split('/').filter(Boolean)
    if (parts.length === 1) return undefined  // /memory itself -- no crumbs
    if (parts[1] === 'reflect') {
      const q = useStore.getState().reflect?.question ?? ''
      const snip = q.length > 40 ? q.slice(0, 40) + '...' : q
      return [
        { label: 'Memory', href: '/memory' },
        { label: 'Reflect' },
        ...(snip ? [{ label: `"${snip}"` }] : []),
      ]
    }
    return [
      { label: 'Memory', href: '/memory' },
      { label: `#${parts[1]}` },
    ]
  }, [location.pathname])
  const hasInteraction = focus && focus.type !== 'conversation'

  // Reusable timeline rail for active-run workspaces (3-column layout). Null
  // when there is no run, so the no-run navigation views are unaffected.
  const timelineRail = run ? (
    <TimelineRail
      phases={phaseNodes}
      activePhaseId={run.phase}
      viewingPhaseId={viewingPhaseId}
      onPhaseClick={setViewingPhaseId}
    />
  ) : null

  // --- Loading ---
  if (!connected) {
    return (
      <div className="app-root">
        <HeaderBar phase="" step="" totalSteps={0} currentStep={0} />
        <div className="single-column"><div className="loading-center">connecting...</div></div>
      </div>
    )
  }

  // --- No active run: page navigation ---
  if (!run) {
    return (
      <div className="app-root">
        <HeaderBar
          phase="" step="" totalSteps={0} currentStep={0}
          mode="navigation"
          navItems={NAV_ITEMS}
          activeNav={page}
          crumbs={memoryCrumbs}
          onNavChange={k => navigate(PATH_BY_KEY[k] ?? '/')}
        />
        {page === 'new-run' && <div className="single-column"><ConnectedNewRunForm /></div>}
        {page === 'sessions' && (
          <div className="single-column">
            <SessionsPage />
          </div>
        )}
        {page === 'memory' && <div className="single-column"><MemoryRoutes /></div>}
        {page === 'settings' && <ConnectedSettingsPage />}
        <Notification />
      </div>
    )
  }

  // --- Active run: workflow views ---
  if (hasInteraction) {
    return (
      <div className="app-root">
        <HeaderBar {...header} onSettingsClick={goToSettings} />
        <div className="workflow-grid workflow-grid--with-rail">
          {timelineRail}
          <div className="content-column"><ElicitationView /></div>
          <ConnectedSidebar />
        </div>
        <Notification />
      </div>
    )
  }

  if (completion) {
    if (completion.success) {
      // Auto-navigation timer is running (3s). Keep workflow-mode header so
      // the phase/step breadcrumb remains visible while the user waits.
      return (
        <div className="app-root">
          <HeaderBar {...header} onSettingsClick={goToSettings} />
          <div className="workflow-grid workflow-grid--with-rail">{timelineRail}<CompletionView /><ConnectedSidebar /></div>
          <Notification />
        </div>
      )
    }
    // Failure: switch to navigation-mode header so nav clicks can clear and
    // navigate. No auto-navigation -- user must take an explicit action.
    const handleNav = async (k: string) => {
      await api.clearRun()
      navigate(PATH_BY_KEY[k] ?? '/')
    }
    const handleBack = async () => {
      await api.clearRun()
      navigate('/')
    }
    return (
      <div className="app-root">
        <HeaderBar
          phase="" step="" totalSteps={0} currentStep={0}
          mode="navigation"
          navItems={NAV_ITEMS}
          activeNav=""
          onNavChange={handleNav}
        />
        <div className="workflow-grid workflow-grid--with-rail">
          {timelineRail}
          <CompletionView onBackToOverview={handleBack} />
          <ConnectedSidebar />
        </div>
        <Notification />
      </div>
    )
  }

  if (reviewingArtifact) {
    return (
      <div className="app-root">
        <HeaderBar {...header} onSettingsClick={goToSettings} />
        <div className="workflow-grid workflow-grid--with-rail">{timelineRail}<ReviewView /><ConnectedSidebar /></div>
        <ConnectedScoutBar />
        <Notification />
      </div>
    )
  }

  return (
    <div className="app-root">
      <HeaderBar {...header} onSettingsClick={goToSettings} />
      <div className="workflow-grid workflow-grid--with-rail">{timelineRail}<ContentStream /><ConnectedSidebar /></div>
      <ConnectedScoutBar />
      <Notification />
    </div>
  )
}
