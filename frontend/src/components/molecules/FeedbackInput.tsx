/**
 * FeedbackInput -- text input for sending feedback/messages to the agent.
 *
 * Sits at the bottom of the content stream. Enter sends, Shift+Enter
 * inserts a newline. Uses the Button atom for the send action.
 *
 * Watches the chatDraft store field: when a YieldPanel row is selected,
 * the parent sets chatDraft to "/<phase-id> ", which FeedbackInput picks
 * up via useEffect, populates the textarea, and focuses it. The user
 * reviews and presses Send -- no auto-submit.
 *
 * /-command support: when availableCommands is provided and the textarea
 * starts with "/", a CommandPalette floats above showing filterable phase
 * commands. Selecting a command inserts "/<id> " into the textarea. On
 * send, /-commands are rewritten into a natural-language instruction
 * before calling onSend.
 *
 * Used in: content stream footer.
 */

import { useState, useRef, useEffect, type KeyboardEvent } from 'react'
import { useStore } from '../../store/index'
import { Button } from '../atoms/Button'
import { CommandPalette } from './CommandPalette'
import './FeedbackInput.css'

interface Command {
  id: string
  description: string
}

interface FeedbackInputProps {
  placeholder?: string
  onSend?: (text: string) => void
  disabled?: boolean
  availableCommands?: Command[]
  onPaletteToggle?: (open: boolean) => void
}

// Parse "/<cmd> <instruction>" and rewrite into a phase-transition message.
// Non-slash input passes through unchanged.
function transformCommand(text: string): string {
  if (!text.startsWith('/')) return text
  const body = text.slice(1)
  const space = body.indexOf(' ')
  const cmd = space === -1 ? body : body.slice(0, space)
  const instruction = space === -1 ? '' : body.slice(space + 1).trim()
  if (instruction) {
    return `The user wishes to transition to phase \`${cmd}\` with instruction: ${instruction}`
  }
  return `The user wishes to transition to phase \`${cmd}\`.`
}

export function FeedbackInput({
  placeholder = 'Send feedback...',
  onSend,
  disabled = false,
  availableCommands,
  onPaletteToggle,
}: FeedbackInputProps) {
  const [text, setText] = useState('')
  const [activeIndex, setActiveIndex] = useState(0)
  const ref = useRef<HTMLTextAreaElement>(null)

  const chatDraft = useStore(s => s.chatDraft)
  const setChatDraft = useStore(s => s.setChatDraft)

  // Pick up draft set by YieldPanel row selections
  useEffect(() => {
    if (chatDraft) {
      setText(chatDraft)
      setChatDraft('')
      ref.current?.focus()
    }
  }, [chatDraft, setChatDraft])

  // Palette open rule: text begins with "/" AND the body (post-slash) has
  // no space. Once a command is selected we insert "/<id> " with a space,
  // which naturally closes the palette so the user can type instructions.
  const paletteOpen = !!(
    availableCommands &&
    availableCommands.length > 0 &&
    text.startsWith('/') &&
    !text.slice(1).includes(' ')
  )

  const filter = paletteOpen ? text.slice(1) : ''
  const filteredCommands = paletteOpen
    ? (availableCommands ?? []).filter(c => c.id.startsWith(filter))
    : []

  // Reset active index when filter changes so the first match is always highlighted.
  useEffect(() => {
    setActiveIndex(0)
  }, [filter])

  // Notify parent whenever palette toggles.
  useEffect(() => {
    onPaletteToggle?.(paletteOpen)
  }, [paletteOpen, onPaletteToggle])

  const send = () => {
    const trimmed = text.trim()
    if (!trimmed || disabled) return
    onSend?.(transformCommand(trimmed))
    setText('')
    ref.current?.focus()
  }

  const selectCommand = (cmd: Command) => {
    const next = `/${cmd.id} `
    setText(next)
    // Re-focus and move the cursor past the trailing space.
    requestAnimationFrame(() => {
      const el = ref.current
      if (el) {
        el.focus()
        el.setSelectionRange(next.length, next.length)
      }
    })
  }

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (paletteOpen) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        if (filteredCommands.length > 0) {
          setActiveIndex(i => (i + 1) % filteredCommands.length)
        }
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        if (filteredCommands.length > 0) {
          setActiveIndex(i => (i - 1 + filteredCommands.length) % filteredCommands.length)
        }
        return
      }
      if (e.key === 'Enter') {
        e.preventDefault()
        const cmd = filteredCommands[activeIndex]
        if (cmd) selectCommand(cmd)
        return
      }
      if (e.key === 'Escape') {
        e.preventDefault()
        setText('')
        return
      }
      // Any other key: default textarea behavior (updates filter).
      return
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  return (
    <div className={`fi${disabled ? ' fi--disabled' : ''}${paletteOpen ? ' fi--focused' : ''}`}>
      {paletteOpen && (
        <CommandPalette
          commands={availableCommands ?? []}
          filter={filter}
          activeIndex={activeIndex}
          onSelect={selectCommand}
          onNavigate={() => {}}
          onDismiss={() => setText('')}
        />
      )}
      <textarea
        ref={ref}
        className="fi-textarea"
        placeholder={placeholder}
        value={text}
        onChange={e => setText(e.target.value)}
        onKeyDown={onKey}
        disabled={disabled}
        rows={1}
      />
      <div className="fi-footer">
        <span className="fi-hint">
          {paletteOpen
            ? '\u2191\u2193 navigate \u00b7 Enter select \u00b7 Esc dismiss'
            : 'Enter to send \u00b7 Shift+Enter for newline'}
        </span>
        <Button
          variant="primary"
          size="sm"
          onClick={send}
          disabled={disabled || !text.trim()}
        >
          Send
        </Button>
      </div>
    </div>
  )
}

export default FeedbackInput
