/**
 * CommandPalette -- floating dropdown anchored above FeedbackInput,
 * showing workflow phase commands filterable by typing.
 *
 * Pure presentational molecule. All state (open/closed, filter,
 * active index) is owned by FeedbackInput. CommandPalette receives
 * the full command list plus the current filter and highlights the
 * item at activeIndex within the filtered result.
 *
 * Clicking an item calls onSelect(command). onNavigate/onDismiss are
 * part of the API contract but not used internally -- FeedbackInput
 * owns the keyboard handling.
 */

import './CommandPalette.css'

interface Command {
  id: string
  description: string
}

interface CommandPaletteProps {
  commands: Command[]
  filter: string
  activeIndex: number
  onSelect: (command: Command) => void
  onNavigate: (direction: 'up' | 'down') => void
  onDismiss: () => void
}

export function CommandPalette(props: CommandPaletteProps) {
  const { commands, filter, activeIndex, onSelect } = props
  const filtered = commands.filter(c => c.id.startsWith(filter))

  return (
    <div className="cp">
      <div className="cp-hint">
        <span className="cp-hint-icon" aria-hidden="true">i</span>
        <span className="cp-hint-text">Select a command or keep typing to filter</span>
      </div>
      {filtered.length === 0 ? (
        <div className="cp-empty">No matching commands</div>
      ) : (
        <div className="cp-items">
          {filtered.map((cmd, i) => (
            <div
              key={cmd.id}
              className={`cp-item${i === activeIndex ? ' cp-item--active' : ''}`}
              // onMouseDown + preventDefault keeps focus on the textarea
              // so the browser doesn't blur it mid-click.
              onMouseDown={e => {
                e.preventDefault()
                onSelect(cmd)
              }}
            >
              <div className="cp-name">
                <span className="cp-slash">/</span>{cmd.id}
              </div>
              <div className="cp-desc">{cmd.description}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default CommandPalette
