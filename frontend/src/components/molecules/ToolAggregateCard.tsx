/**
 * ToolAggregateCard — a two-pane card that groups consecutive exploration
 * tool calls (read, grep, ls) into a single visual unit.
 *
 * Structure: a header with an "explore" label, a formatted operation
 * count, an optional running indicator, and an optional elapsed duration;
 * below the header, a two-column grid body with a 240px stats pane on
 * the left and a flexible log pane on the right. The panes are slot
 * props (statsPane, logPane) — the caller composes ToolStatBlock and
 * ToolLogRow children directly into these slots.
 *
 * Source accent: the card has a 3px orange left border at all times,
 * following the "left border = content source" convention — tool calls
 * are agent output, so the card inherits the same source accent as
 * ProseCard. The border color does NOT change when the card is active.
 *
 * Active state: when the card's aggregate contains an in-flight
 * operation, the caller passes runningLabel (a short human-readable
 * string like "reading projections.py") and the card renders a
 * pulsing orange dot plus the label in its header. The caller is also
 * responsible for marking the appropriate ToolStatBlock as active and
 * the in-flight ToolLogRow as status="running" inside the slot props —
 * the card does not reach into its slots to do this. The three
 * activation signals (header indicator, active stat block, running log
 * row) together tell the user something is happening; no outer-border
 * change participates.
 *
 * Used in: the content stream, replacing runs of consecutive
 * ToolCallRow molecules. The grouping logic that decides when to render
 * a card (vs. individual rows) lives in a utility function (prompt 8).
 */

import type { ReactNode } from 'react'
import './ToolAggregateCard.css'

interface ToolAggregateCardProps {
  /** Number of operations in this aggregate. Formatted by the card as
   *  "N operation" or "N operations". The card handles pluralization. */
  operationCount: number
  /** When set, the card is in its active state: the header renders the
   *  pulsing dot plus this label. Typical values: "reading projections.py",
   *  "grepping for phase context", "listing koan/phases". When undefined,
   *  the header's running indicator is not rendered. */
  runningLabel?: string
  /** Pre-formatted wall-clock duration for the aggregate, e.g. "1m 12s",
   *  "3m 24s". Shown in the header for both completed and active cards.
   *  The caller handles formatting. */
  elapsed?: string
  /** The left pane content. Typically a stack of ToolStatBlock elements,
   *  one per tool family present in the aggregate. */
  statsPane: ReactNode
  /** The right pane content. Typically a stack of ToolLogRow elements
   *  in chronological order. */
  logPane: ReactNode
}

export function ToolAggregateCard({
  operationCount,
  runningLabel,
  elapsed,
  statsPane,
  logPane,
}: ToolAggregateCardProps) {
  const countText = `${operationCount} operation${operationCount === 1 ? '' : 's'}`
  return (
    <div className="tac">
      <div className="tac-header">
        <span className="tac-label">explore</span>
        <span className="tac-count">{countText}</span>
        <span className="tac-spacer" />
        {runningLabel && (
          <span className="tac-running">
            {/* Inline pulsing dot — intentionally NOT StatusDot. See file header. */}
            <span className="tac-running-dot" aria-label="running" />
            <span className="tac-running-label">{runningLabel}</span>
          </span>
        )}
        {elapsed && <span className="tac-elapsed">{elapsed}</span>}
      </div>
      <div className="tac-body">
        <div className="tac-stats-pane">{statsPane}</div>
        <div className="tac-log-pane">{logPane}</div>
      </div>
    </div>
  )
}

export default ToolAggregateCard
