/**
 * HeaderBar — the fixed navy bar at the top of every view.
 *
 * Two modes:
 * - workflow: breadcrumb nav with phase/step/progress, orchestrator
 *   status, elapsed time, settings gear button.
 * - navigation: top-level page navigation links (New run, Sessions,
 *   Settings). No workflow-specific controls.
 *
 * Used in: app shell, rendered above all content views.
 */

import { LogoMark } from '../atoms/LogoMark'
import { StatusDot } from '../atoms/StatusDot'
import { BreadcrumbNav } from '../molecules/BreadcrumbNav'
import './HeaderBar.css'

interface HeaderBarProps {
  // Workflow mode props
  phase: string
  step: string
  totalSteps: number
  currentStep: number
  orchestratorModel?: string
  elapsed?: string
  onSettingsClick?: () => void

  // Mode switching
  mode?: 'workflow' | 'navigation'
  navItems?: { label: string; key: string }[]
  activeNav?: string
  onNavChange?: (key: string) => void
}

const GearIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <circle cx="12" cy="12" r="3"
      stroke="rgba(240,232,216,0.6)" strokeWidth="2" /* warm off-white gear stroke — from design-system.md header spec */ />
    <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"
      stroke="rgba(240,232,216,0.6)" strokeWidth="2" strokeLinecap="round" /* same warm off-white */ />
  </svg>
)

export function HeaderBar({
  phase,
  step,
  totalSteps,
  currentStep,
  orchestratorModel,
  elapsed,
  onSettingsClick,
  mode = 'workflow',
  navItems,
  activeNav,
  onNavChange,
}: HeaderBarProps) {
  return (
    <header className="hb">
      <div className="hb-inner">
        <div className="hb-left">
          <div className="hb-logo">
            <LogoMark />
            <span className="hb-wordmark">koan</span>
          </div>
          <span className="hb-divider" />

          {mode === 'workflow' ? (
            <BreadcrumbNav
              phase={phase}
              step={step}
              totalSteps={totalSteps}
              currentStep={currentStep}
            />
          ) : (
            <div className="hb-nav">
              {navItems?.map(item => (
                <button
                  key={item.key}
                  type="button"
                  className={`hb-nav-link${item.key === activeNav ? ' hb-nav-link--active' : ''}`}
                  onClick={() => onNavChange?.(item.key)}
                >
                  {item.label}
                </button>
              ))}
            </div>
          )}
        </div>

        {mode === 'workflow' && (
          <div className="hb-right">
            {orchestratorModel && (
              <div className="hb-orchestrator">
                <StatusDot status="done" size="sm" />
                <span className="hb-model">{orchestratorModel}</span>
              </div>
            )}
            {elapsed && <span className="hb-elapsed">{elapsed}</span>}
            <button
              className="hb-settings"
              onClick={onSettingsClick}
              aria-label="Settings"
            >
              <GearIcon />
            </button>
          </div>
        )}
      </div>
    </header>
  )
}

export default HeaderBar
