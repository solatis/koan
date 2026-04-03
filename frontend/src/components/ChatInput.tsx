import { useState, useRef, useEffect, KeyboardEvent } from 'react'
import { useStore } from '../store/index'
import { sendChatMessage } from '../api/client'

export function ChatInput() {
  const [text, setText] = useState('')
  const [sending, setSending] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const run = useStore(s => s.run)
  const isDisabled = !run || run.completion !== null || sending

  // Auto-resize textarea to fit content
  useEffect(() => {
    const ta = textareaRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = Math.min(ta.scrollHeight, 120) + 'px'
  }, [text])

  async function handleSend() {
    const msg = text.trim()
    if (!msg || isDisabled) return

    setSending(true)
    try {
      await sendChatMessage(msg)
      setText('')
    } catch (e) {
      // Silently ignore network errors; message may still be buffered
    } finally {
      setSending(false)
    }
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="chat-input-area">
      <div className="chat-input-box">
        <textarea
          ref={textareaRef}
          className="chat-input-textarea"
          value={text}
          onChange={e => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={isDisabled ? 'No active run' : 'Send feedback…'}
          disabled={isDisabled}
          rows={1}
        />
        <div className="chat-input-footer">
          <span className="chat-input-hint">Enter to send · Shift+Enter for newline</span>
          <button
            className="chat-input-send"
            onClick={handleSend}
            disabled={isDisabled || !text.trim()}
          >
            Send
          </button>
        </div>
      </div>
    </div>
  )
}
