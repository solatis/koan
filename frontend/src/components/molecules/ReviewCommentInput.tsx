/**
 * ReviewCommentInput -- inline comment form rendered below a ReviewBlock
 * when the user clicks the gutter "+" button. Auto-focuses on mount.
 */

import { useEffect, useRef, useState } from 'react'
import { Button } from '../atoms/Button'
import './ReviewCommentInput.css'

interface ReviewCommentInputProps {
  onAdd: (text: string) => void
  onCancel: () => void
}

export function ReviewCommentInput({ onAdd, onCancel }: ReviewCommentInputProps) {
  const [text, setText] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    textareaRef.current?.focus()
  }, [])

  const handleAdd = () => {
    onAdd(text)
    setText('')
  }

  return (
    <div className="rci">
      <textarea
        ref={textareaRef}
        className="rci-textarea"
        value={text}
        onChange={e => setText(e.target.value)}
        placeholder="Add a comment on this block..."
      />
      <div className="rci-actions">
        <Button variant="secondary" size="xs" onClick={onCancel}>Cancel</Button>
        <Button variant="primary" size="xs" onClick={handleAdd}>Add comment</Button>
      </div>
    </div>
  )
}

export default ReviewCommentInput
