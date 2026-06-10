/**
 * InlineNotice — a one-line warning strip.
 *
 * Used by the New Run config-incomplete gate ("Assign a model to all three
 * roles...") and the add-connection backend note. Reusable anywhere a
 * non-blocking warning with an optional action link is needed.
 */

import './InlineNotice.css'
import type { ReactNode } from 'react'

interface InlineNoticeProps {
  message: ReactNode
  action?: { label: string; onClick: () => void }
}

export function InlineNotice({ message, action }: InlineNoticeProps) {
  return (
    <div className="mol-inline-notice" role="status">
      <svg
        className="mol-inline-notice__icon"
        viewBox="0 0 24 24"
        fill="none"
        strokeWidth="2"
        strokeLinecap="round"
        aria-hidden="true"
      >
        <path d="M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" />
      </svg>
      <span className="mol-inline-notice__message">{message}</span>
      {action && (
        <button
          type="button"
          className="mol-inline-notice__action"
          onClick={action.onClick}
        >
          {action.label}
        </button>
      )}
    </div>
  )
}

export default InlineNotice
