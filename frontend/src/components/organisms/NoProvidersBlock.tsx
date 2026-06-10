/**
 * NoProvidersBlock — the first-run / cold-start gate.
 *
 * Shown by NewRunForm when ZERO connections exist: a full takeover of the New
 * Run content area (distinct from the incomplete-config state, which keeps the
 * form and shows an InlineNotice instead). Presentational; the parent supplies
 * the navigation callback.
 */

import './NoProvidersBlock.css'
import { Button } from '../atoms/Button'
import { RoleCard } from '../molecules/RoleCard'

export interface NoProvidersBlockProps {
  onGoToSettings: () => void
}

const WarningTriangle = () => (
  <svg
    width="21"
    height="21"
    viewBox="0 0 24 24"
    fill="none"
    stroke="var(--text-danger-body)"
    strokeWidth="2"
    strokeLinecap="round"
    aria-hidden="true"
  >
    <path d="M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" />
  </svg>
)

export function NoProvidersBlock({ onGoToSettings }: NoProvidersBlockProps) {
  return (
    <div className="org-no-providers-block">
      <div className="org-no-providers-block__mark">
        <WarningTriangle />
      </div>
      <h2 className="org-no-providers-block__heading">No providers configured</h2>
      <p className="org-no-providers-block__body">
        koan needs at least one connection before it can run. Add a provider,
        then assign models to the three roles.
      </p>
      <div className="org-no-providers-block__roles">
        <RoleCard role="strong" variant="not-set" />
        <RoleCard role="standard" variant="not-set" />
        <RoleCard role="cheap" variant="not-set" />
      </div>
      <Button variant="primary" size="md" onClick={onGoToSettings}>
        Go to Settings
      </Button>
    </div>
  )
}

export default NoProvidersBlock
