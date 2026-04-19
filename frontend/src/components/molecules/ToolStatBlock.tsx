/**
 * ToolStatBlock — per-tool-family statistics block for the left pane of
 * ToolAggregateCard.
 *
 * Displays aggregated scope information for one tool family (read, grep,
 * or ls): operation count in the header, then free-form meta lines below
 * aligned under the tool name. Each block represents one tool family's
 * presence inside a single ToolAggregateCard; the card renders one block
 * per family that has at least one operation.
 *
 * Active state: when the currently-running operation in the enclosing
 * ToolAggregateCard belongs to this block's tool family, the caller
 * passes active={true} and the tool name renders in orange. The dot and
 * op count are not affected. Only one block within a card can be active
 * at a time — enforcement is the caller's responsibility.
 *
 * Used in: ToolAggregateCard left pane (not yet built — this molecule
 * is delivered ahead of the card).
 */

import { StatusDot } from '../atoms/StatusDot'
import './ToolStatBlock.css'

interface ToolStatBlockProps {
  /** Tool family. Drives the StatusDot color. */
  type: 'read' | 'grep' | 'ls'
  /** Display name shown next to the dot. Currently mirrors `type` in all
   *  call sites — the two are kept separate per the design-system spec
   *  to allow future alternative display names without an API break. */
  name: string
  /** Pre-formatted operation count, e.g. "4 ops", "1 op". The caller
   *  handles pluralization and number-to-string formatting. */
  opCount: string
  /** One or more meta lines describing aggregate scope. Each line is
   *  a pre-formatted string, e.g. "612 lines · 24.7 KB",
   *  "3 files touched", "76 matches". Empty array is allowed; the
   *  block then renders with only its header row. */
  metaLines: string[]
  /** When true, the tool name renders in orange. Set by the parent
   *  ToolAggregateCard when the in-flight operation belongs to this
   *  tool family. */
  active?: boolean
}

export function ToolStatBlock({
  type,
  name,
  opCount,
  metaLines,
  active = false,
}: ToolStatBlockProps) {
  const cls = `tsb${active ? ' tsb--active' : ''}`
  return (
    <div className={cls}>
      <div className="tsb-header">
        <StatusDot status={type} size="md" />
        <span className="tsb-name">{name}</span>
        <span className="tsb-opcount">{opCount}</span>
      </div>
      {metaLines.length > 0 && (
        <div className="tsb-meta">
          {metaLines.map((line, i) => (
            <div key={i} className="tsb-meta-line">{line}</div>
          ))}
        </div>
      )}
    </div>
  )
}

export default ToolStatBlock
