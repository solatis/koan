import { useState, useRef, useEffect, type KeyboardEvent } from 'react'
import { useStore } from '../../store/index'
import { useFileAttachment } from '../../hooks/useFileAttachment'
import { Button } from '../atoms/Button'
import { FileChip } from '../atoms/FileChip'
import { CommandPalette } from './CommandPalette'
import './FeedbackInput.css'

interface Command {
  id: string
  description: string
}

interface FeedbackInputProps {
  placeholder?: string
  onSend?: (text: string, attachments?: string[]) => void
  disabled?: boolean
  availableCommands?: Command[]
  onPaletteToggle?: (open: boolean) => void
}

/**
 * Transform a slash-command input into a structured chat message
 * the orchestrator (an LLM) parses to decide which MCP tool to call.
 *
 * - Phase commands (e.g. `/plan-spec instruction`) become
 *   "The user wishes to transition to phase `plan-spec` ..."
 * - Workflow commands (e.g. `/workflow:plan instruction`) become
 *   "The user wishes to switch to workflow `plan` ..."
 *
 * Non-slash text passes through unchanged.
 */
function transformCommand(text: string): string {
  if (!text.startsWith('/')) return text
  const body = text.slice(1)
  const space = body.indexOf(' ')
  const cmd = space === -1 ? body : body.slice(0, space)
  const instruction = space === -1 ? '' : body.slice(space + 1).trim()

  // Workflow commands have the form "workflow:<name>".
  const WORKFLOW_PREFIX = 'workflow:'
  if (cmd.startsWith(WORKFLOW_PREFIX)) {
    const workflow = cmd.slice(WORKFLOW_PREFIX.length)
    if (instruction) {
      return `The user wishes to switch to workflow \`${workflow}\` with instruction: ${instruction}`
    }
    return `The user wishes to switch to workflow \`${workflow}\`.`
  }

  if (instruction) {
    return `The user wishes to transition to phase \`${cmd}\` with instruction: ${instruction}`
  }
  return `The user wishes to transition to phase \`${cmd}\`.`
}

const PaperclipIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.49" />
  </svg>
)

const UploadIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
    <polyline points="17 8 12 3 7 8" />
    <line x1="12" y1="3" x2="12" y2="15" />
  </svg>
)

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

  const attach = useFileAttachment()

  useEffect(() => {
    if (chatDraft) {
      setText(chatDraft)
      setChatDraft('')
      ref.current?.focus()
    }
  }, [chatDraft, setChatDraft])

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

  useEffect(() => {
    setActiveIndex(0)
  }, [filter])

  useEffect(() => {
    onPaletteToggle?.(paletteOpen)
  }, [paletteOpen, onPaletteToggle])

  const send = () => {
    const trimmed = text.trim()
    if (!trimmed || disabled) return
    const ids = attach.fileIds.length > 0 ? attach.fileIds : undefined
    onSend?.(transformCommand(trimmed), ids)
    setText('')
    attach.clearFiles()
    ref.current?.focus()
  }

  const selectCommand = (cmd: Command) => {
    const next = `/${cmd.id} `
    setText(next)
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
      return
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  const cls = [
    'fi',
    disabled && 'fi--disabled',
    paletteOpen && 'fi--focused',
    attach.dragging && 'fi--dragging',
  ].filter(Boolean).join(' ')

  return (
    <div className={cls} {...attach.dragProps}>
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

      {attach.dragging && (
        <div className="fi-drop-overlay">
          <UploadIcon />
          <span className="fi-drop-label">Drop to attach</span>
        </div>
      )}

      <div className="fi-textarea-wrap">
        <textarea
          ref={ref}
          className="fi-textarea"
          placeholder={placeholder}
          value={text}
          onChange={e => setText(e.target.value)}
          onKeyDown={onKey}
          onPaste={attach.onPaste}
          disabled={disabled}
          rows={1}
        />
        <button
          className="fi-attach-btn"
          onClick={attach.openPicker}
          title="Attach files"
          type="button"
          disabled={disabled}
        >
          <PaperclipIcon />
        </button>
        <input
          ref={attach.inputRef}
          type="file"
          multiple
          className="fi-file-input"
          onChange={attach.onInputChange}
          tabIndex={-1}
        />
      </div>

      {attach.files.length > 0 && (
        <div className="fi-chips">
          {attach.files.map(f => (
            <FileChip
              key={f.id}
              name={f.name}
              size={f.size}
              state={f.state}
              onRemove={() => attach.removeFile(f.id)}
            />
          ))}
        </div>
      )}

      <div className="fi-footer">
        <span className="fi-hint">
          {paletteOpen
            ? '↑↓ navigate · Enter select · Esc dismiss'
            : 'Enter to send · Shift+Enter for newline'}
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
