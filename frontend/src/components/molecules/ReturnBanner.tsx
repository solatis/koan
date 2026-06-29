/**
 * ReturnBanner — a clickable banner shown at the top of the content area when
 * the user is viewing historical phase content while another phase is active.
 * Clicking it navigates back to the active phase.
 *
 * The pulsing orange dot signals live activity in the active phase.
 *
 * Used in: content column, above PhaseTitleBar (only while viewing history).
 */

import './ReturnBanner.css'

interface ReturnBannerProps {
  activePhase: string
  onClick: () => void
}

export function ReturnBanner({ activePhase, onClick }: ReturnBannerProps) {
  return (
    <div className="rb" onClick={onClick}>
      <span className="rb__dot" />
      <span className="rb__text">
        Active: <span className="rb__phase">{activePhase}</span> is running
      </span>
      <span className="rb__arrow" aria-hidden="true">
        →
      </span>
    </div>
  )
}

export default ReturnBanner
