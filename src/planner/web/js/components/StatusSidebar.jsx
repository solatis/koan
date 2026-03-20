import { useStore } from '../store.js'

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

  // Only render when there is an active subagent.
  if (!subagent) return null

  const isIntake = phase === 'intake'

  return (
    <aside class="status-sidebar">
      <div class="sidebar-heading">Phase Status</div>
      {isIntake && intakeProgress
        ? <IntakeStatus progress={intakeProgress} />
        : <GenericStatus phase={phase} />
      }
    </aside>
  )
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

// -- Generic status for decompose / review / execute phases --

function GenericStatus({ phase }) {
  const label =
    phase === 'decomposition' ? 'Decomposing into stories'
    : phase === 'review'      ? 'Review in progress'
    : phase === 'executing'   ? 'Executing stories'
    : phase ?? 'In progress'

  return (
    <SidebarSection label="Status">
      <div class="sidebar-value">{label}</div>
      <div class="sidebar-summary" style={{ marginTop: '6px' }}>Phase in progress…</div>
    </SidebarSection>
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
