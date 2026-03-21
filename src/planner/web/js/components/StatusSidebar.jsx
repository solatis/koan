// Single home for all live-mode status context.
//
// Renders in the right column whenever a pipeline phase is active. Absorbs
// the three removed components: agent identity (was SubagentMeta), elapsed
// timer (was Timer), and phase progress (was ProgressBar + per-phase panels).
//
// Store slices read: phase (visibility gate + dispatch), subagent (identity
// section), intakeProgress (intake-specific data), stories (decompose/execute).
// The sidebar stays mounted between subagent spawns — phase status is visible
// even when subagent is null.

import { useState, useEffect } from 'preact/hooks'
import { useStore } from '../store.js'
import { shortenModel, formatTokens, formatElapsed } from '../lib/utils.js'

// Maps confidence level to number of filled segments (out of 5) and accent colour.
const CONFIDENCE_DISPLAY = {
  exploring: { segments: 0, color: 'var(--text-ghost)' },
  low:       { segments: 1, color: 'var(--red)' },
  medium:    { segments: 3, color: 'var(--orange)' },
  high:      { segments: 4, color: 'var(--green)' },
  certain:   { segments: 5, color: 'var(--green)' },
}

// Default summary text per sub-phase shown while the agent is working.
const SUBPHASE_SUMMARY = {
  extract:    'Reading conversation to understand the task…',
  scout:      'Exploring codebase via parallel scouts…',
  deliberate: 'Analyzing findings, preparing questions…',
  reflect:    'Verifying completeness of understanding…',
  questions:  'Waiting for user response…',
  synthesize: 'Writing context.md…',
}

export function StatusSidebar() {
  const subagent = useStore(s => s.subagent)
  const phase = useStore(s => s.phase)
  const intakeProgress = useStore(s => s.intakeProgress)
  const stories = useStore(s => s.stories)

  // Render whenever there is an active phase in live mode.
  if (!phase) return null

  return (
    <aside class="status-sidebar">
      <div class="sidebar-heading">Phase Status</div>
      {subagent && <AgentIdentity subagent={subagent} />}
      <PhaseStatus phase={phase} intakeProgress={intakeProgress} stories={stories} />
    </aside>
  )
}

// -- Agent identity section (role, model, step, tokens, elapsed timer) --

function AgentIdentity({ subagent }) {
  const startedAt = subagent.startedAt
  const [now, setNow] = useState(Date.now())

  useEffect(() => {
    if (!startedAt) return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [startedAt])

  const stepLabel = subagent.stepName || (subagent.step && subagent.totalSteps
    ? `Step ${subagent.step}/${subagent.totalSteps}`
    : null)

  const elapsed = startedAt ? formatElapsed(Math.max(0, now - startedAt)) : '—'

  return (
    <div class="sidebar-agent">
      <div>
        <span class="sidebar-agent-role">{subagent.role}</span>
        {subagent.model && (
          <span class="sidebar-agent-model"> · {shortenModel(subagent.model)}</span>
        )}
      </div>
      {stepLabel && (
        <div class="sidebar-agent-step">{stepLabel}</div>
      )}
      <div class="sidebar-agent-stats">
        <span>↑{formatTokens(subagent.tokensSent || 0)} ↓{formatTokens(subagent.tokensReceived || 0)}</span>
        <span>{elapsed}</span>
      </div>
      <div class="sidebar-divider" />
    </div>
  )
}

// -- Phase-specific status dispatcher --

function PhaseStatus({ phase, intakeProgress, stories }) {
  if (phase === 'intake') {
    return intakeProgress
      ? <IntakeStatus progress={intakeProgress} />
      : <GenericStatus phase={phase} />
  }
  switch (phase) {
    case 'brief':
      return <BriefStatus />
    case 'decomposition':
      return <DecomposeStatus stories={stories} />
    case 'executing':
      return <ExecuteStatus stories={stories} />
    default:
      return <GenericStatus phase={phase} />
  }
}

// -- Intake-specific status: confidence meter, iteration dots, sub-phase, summary --

function IntakeStatus({ progress }) {
  const { confidence, iteration, subPhase, intakeDone } = progress
  const conf = CONFIDENCE_DISPLAY[confidence] ?? CONFIDENCE_DISPLAY.exploring

  return (
    <>
      <SidebarSection label="Confidence">
        <div class="sidebar-segments">
          {Array.from({ length: 5 }, (_, i) => (
            <div
              key={i}
              class="sidebar-segment"
              style={{ background: i < conf.segments ? conf.color : 'var(--border)' }}
            />
          ))}
        </div>
        <div class="sidebar-value" style={{ color: conf.color }}>
          {confidence ?? 'exploring'}
        </div>
      </SidebarSection>

      {iteration > 0 && (
        <SidebarSection label="Iteration">
          <div class="sidebar-dots">
            {Array.from({ length: 4 }, (_, i) => (
              <div
                key={i}
                class="sidebar-dot"
                style={{ background: i < iteration ? 'var(--blue)' : 'var(--border)' }}
              />
            ))}
          </div>
          <div class="sidebar-value">Round {iteration} of 4</div>
        </SidebarSection>
      )}

      {subPhase && (
        <SidebarSection label="Sub-phase">
          <div class="sidebar-value" style={{ color: 'var(--purple)' }}>{subPhase}</div>
        </SidebarSection>
      )}

      <div class="sidebar-divider" />

      <SidebarSection label="Summary">
        <div class="sidebar-summary">
          {intakeDone
            ? 'Intake complete.'
            : (SUBPHASE_SUMMARY[subPhase] ?? 'Working…')}
        </div>
      </SidebarSection>
    </>
  )
}

// -- Brief phase status --

function BriefStatus() {
  return (
    <>
      <SidebarSection label="Status">
        <div class="sidebar-value">Drafting epic brief…</div>
      </SidebarSection>
      <div class="sidebar-divider" />
      <SidebarSection label="Summary">
        <div class="sidebar-summary">Synthesizing requirements into a brief.</div>
      </SidebarSection>
    </>
  )
}

// -- Decomposition phase status --

function DecomposeStatus({ stories }) {
  const count = stories ? stories.length : 0
  return (
    <>
      <SidebarSection label="Status">
        <div class="sidebar-value">
          {count > 0 ? `${count} ${count === 1 ? 'story' : 'stories'} identified` : 'Decomposing…'}
        </div>
      </SidebarSection>
      <div class="sidebar-divider" />
      <SidebarSection label="Summary">
        <div class="sidebar-summary">Breaking the epic into stories.</div>
      </SidebarSection>
    </>
  )
}

// -- Execute phase status --

function ExecuteStatus({ stories }) {
  const total = stories ? stories.length : 0
  const complete = stories ? stories.filter(s => s.status === 'done').length : 0
  const active = stories ? stories.filter(s =>
    s.status === 'selected' || s.status === 'planning' ||
    s.status === 'executing' || s.status === 'verifying'
  ).length : 0

  return (
    <>
      <SidebarSection label="Progress">
        <div class="sidebar-value">
          {total > 0
            ? `${complete}/${total} complete${active > 0 ? ` · ${active} active` : ''}`
            : 'Executing stories…'}
        </div>
      </SidebarSection>
      <div class="sidebar-divider" />
      <SidebarSection label="Summary">
        <div class="sidebar-summary">Implementing stories in parallel.</div>
      </SidebarSection>
    </>
  )
}

// -- Generic status for phases without a dedicated widget --

function GenericStatus({ phase }) {
  const label = phase === 'review' ? 'Review in progress' : phase ?? 'In progress'

  return (
    <>
      <SidebarSection label="Status">
        <div class="sidebar-value">{label}</div>
      </SidebarSection>
      <div class="sidebar-divider" />
      <SidebarSection label="Summary">
        <div class="sidebar-summary">Phase in progress…</div>
      </SidebarSection>
    </>
  )
}

// -- Shared section wrapper --

function SidebarSection({ label, children }) {
  return (
    <div class="sidebar-section">
      <div class="sidebar-label">{label}</div>
      {children}
    </div>
  )
}
