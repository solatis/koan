import React, { useEffect, useRef } from 'react'
import './FindBar.css'

interface FindBarProps {
  query: string
  onQueryChange: (q: string) => void
  matchCount: number
  /** 1-based current match index; 0 when no matches or query empty. */
  currentMatch: number
  onPrev: () => void
  onNext: () => void
  onClose: () => void
  onCopyTranscript: () => void
}

/**
 * FindBar -- presentational find/copy toolbar.
 *
 * Controlled via props only; reads no store state and calls no API directly.
 * The parent (ContentStream) owns find state, match computation, scrolling,
 * and clipboard writing -- this component is a pure UI shell.
 *
 * Keyboard shortcuts handled here (single-line input convention):
 *   Enter           -> onNext
 *   Shift+Enter     -> onPrev
 *   Escape          -> onClose
 */
export function FindBar({
  query,
  onQueryChange,
  matchCount,
  currentMatch,
  onPrev,
  onNext,
  onClose,
  onCopyTranscript,
}: FindBarProps) {
  const inputRef = useRef<HTMLInputElement>(null)

  // Auto-focus when the bar mounts (Cmd/Ctrl+F opens it).
  useEffect(() => {
    inputRef.current?.focus()
    inputRef.current?.select()
  }, [])

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Escape') {
      e.preventDefault()
      onClose()
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (e.shiftKey) onPrev()
      else onNext()
    }
  }

  const noMatches = query.length > 0 && matchCount === 0
  const countLabel = query.length === 0
    ? ''
    : matchCount === 0
      ? '0 matches'
      : `${currentMatch}/${matchCount}`

  return (
    <div className="fb" role="search" aria-label="Find in conversation">
      <input
        ref={inputRef}
        className="fb-input"
        type="text"
        placeholder="Find..."
        value={query}
        onChange={e => onQueryChange(e.target.value)}
        onKeyDown={onKeyDown}
        aria-label="Search query"
        // Highlight the count label in a muted red tone when query has no matches
        // by applying a data attribute; CSS targets it below via the parent.
        data-no-matches={noMatches ? 'true' : undefined}
      />
      {query.length > 0 && (
        <span className="fb-count">{countLabel}</span>
      )}
      <div className="fb-sep" />
      <button
        className="fb-btn"
        onClick={onPrev}
        disabled={matchCount === 0}
        title="Previous match (Shift+Enter)"
        aria-label="Previous match"
      >
        ^
      </button>
      <button
        className="fb-btn"
        onClick={onNext}
        disabled={matchCount === 0}
        title="Next match (Enter)"
        aria-label="Next match"
      >
        v
      </button>
      <div className="fb-sep" />
      <button
        className="fb-btn"
        onClick={onCopyTranscript}
        title="Copy full transcript"
        aria-label="Copy transcript"
      >
        Copy
      </button>
      <button
        className="fb-btn fb-btn--close"
        onClick={onClose}
        title="Close find bar (Escape)"
        aria-label="Close find bar"
      >
        x
      </button>
    </div>
  )
}
