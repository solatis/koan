/**
 * ReviewBlock -- wraps a single rendered markdown block inside the
 * ReviewPanel. The whole block is a click target for opening a comment
 * input; the gutter "+" button is a visual hint that appears on hover.
 * Text selection within the block is preserved (clicks that produce a
 * selection do not fire the open handler).
 */

import type { MouseEvent, ReactNode } from 'react'
import './ReviewBlock.css'

interface ReviewBlockProps {
  hasComments: boolean
  isActive: boolean
  onClickGutter: () => void
  children: ReactNode
}

export function ReviewBlock({ hasComments: _hasComments, isActive, onClickGutter, children }: ReviewBlockProps) {
  const cls = `rb${isActive ? ' rb--active' : ''}`

  const handleClick = (e: MouseEvent) => {
    const selection = window.getSelection()
    if (selection && selection.toString().length > 0) return
    if ((e.target as HTMLElement).closest('.rb-gutter')) return
    if ((e.target as HTMLElement).closest('.rci')) return
    if ((e.target as HTMLElement).closest('.rc-comment')) return
    onClickGutter()
  }

  const handleGutterClick = (e: MouseEvent) => {
    e.stopPropagation()
    onClickGutter()
  }

  return (
    <div className={cls} onClick={handleClick}>
      <button type="button" className="rb-gutter" onClick={handleGutterClick} aria-label="Add comment">+</button>
      <div className="rb-content">{children}</div>
    </div>
  )
}

export default ReviewBlock
