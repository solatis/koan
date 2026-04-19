/**
 * ReviewPanel -- full-width artifact review surface that takes over
 * the content column. Renders a markdown document, wraps each top-level
 * block in a ReviewBlock, and tracks per-block comments and an optional
 * overall summary until the user submits or closes the review.
 */

import { createContext, useContext, useMemo, useRef, useState } from 'react'
import type { JSX, ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { Button } from '../atoms/Button'
import { ReviewBlock } from '../molecules/ReviewBlock'
import { ReviewComment } from '../molecules/ReviewComment'
import { ReviewCommentInput } from '../molecules/ReviewCommentInput'

import './ReviewPanel.css'

// Published as `true` inside the subtree of any ReviewBlock so that nested
// markdown elements (e.g. a <p> inside an <li> inside a wrapped <ul>) render
// as plain HTML instead of stacking a second gutter button on top.
const NestedCtx = createContext(false)

export interface ReviewSubmitPayload {
  comments: { blockIndex: number; text: string; blockPreview: string }[]
  summary: string
}

interface ReviewPanelProps {
  path: string
  content: string
  isNew?: boolean
  onSubmit: (payload: ReviewSubmitPayload) => void
  onClose: () => void
}

// ---------------------------------------------------------------------------

const countComments = (comments: Record<number, string[]>): number =>
  Object.values(comments).reduce((n, arr) => n + arr.length, 0)

const pluralize = (n: number, unit: string): string =>
  `${n} ${unit}${n !== 1 ? 's' : ''}`

const hintFor = (n: number): string =>
  n === 0
    ? 'No comments yet -- click any block above'
    : `${pluralize(n, 'inline comment')} will be submitted`

const badgeLabel = (n: number): string => pluralize(n, 'comment')

// Collect per-block comments into a flat payload, attaching a preview of
// the anchor block text so the backend can locate the block in source.
const collectSubmit = (
  comments: Record<number, string[]>,
  body: HTMLDivElement | null,
): ReviewSubmitPayload['comments'] => {
  const blocks = body?.querySelectorAll('.rb') ?? []
  return Object.entries(comments).flatMap(([key, texts]) => {
    const idx = Number(key)
    const el = blocks[idx] as HTMLElement | undefined
    const preview = (el?.querySelector('.rb-content')?.textContent ?? '').slice(0, 200)
    return texts.map(text => ({ blockIndex: idx, text, blockPreview: preview }))
  })
}

// ---------------------------------------------------------------------------

export function ReviewPanel({ path, content, isNew, onSubmit, onClose }: ReviewPanelProps) {
  const [activeBlock, setActiveBlock] = useState<number | null>(null)
  const [comments, setComments] = useState<Record<number, string[]>>({})
  const [summary, setSummary] = useState('')
  const bodyRef = useRef<HTMLDivElement>(null)

  // Reset the block counter on every render so index assignments stay
  // stable across re-renders (state is keyed on index).
  const counterRef = useRef(0)
  counterRef.current = 0

  const addComment = (idx: number, text: string) => {
    if (!text.trim()) {
      setActiveBlock(null)
      return
    }
    setComments(prev => ({ ...prev, [idx]: [...(prev[idx] ?? []), text] }))
    setActiveBlock(null)
  }

  const deleteComment = (blockIdx: number, commentIdx: number) => {
    setComments(prev => {
      const blockComments = [...(prev[blockIdx] ?? [])]
      blockComments.splice(commentIdx, 1)
      const next = { ...prev }
      if (blockComments.length === 0) {
        delete next[blockIdx]
      } else {
        next[blockIdx] = blockComments
      }
      return next
    })
  }

  const toggleBlock = (idx: number) =>
    setActiveBlock(cur => (cur === idx ? null : idx))

  const wrapBlock = (node: ReactNode): ReactNode => {
    const idx = counterRef.current++
    const blockComments = comments[idx] ?? []
    const isActive = activeBlock === idx
    return (
      <ReviewBlock
        key={idx}
        hasComments={blockComments.length > 0}
        isActive={isActive}
        onClickGutter={() => toggleBlock(idx)}
      >
        <NestedCtx.Provider value={true}>
          {node}
          {blockComments.map((text, i) => (
            <ReviewComment key={i} text={text} onDelete={() => deleteComment(idx, i)} />
          ))}
          {isActive && (
            <ReviewCommentInput
              onAdd={text => addComment(idx, text)}
              onCancel={() => setActiveBlock(null)}
            />
          )}
        </NestedCtx.Provider>
      </ReviewBlock>
    )
  }

  // One renderer per markdown tag: wraps as a ReviewBlock when it is a
  // top-level block, or renders as plain HTML when it is already inside
  // another ReviewBlock (the NestedCtx check). Memoized so that parent
  // re-renders during SSE streaming don't give react-markdown fresh
  // component types -- that would unmount and remount every .rb block and
  // cause visible flicker.
  const mdComponents = useMemo(() => {
    const renderAs = (Tag: keyof JSX.IntrinsicElements) =>
      function TagRenderer({ children }: { children?: ReactNode }) {
        const nested = useContext(NestedCtx)
        const el = <Tag>{children}</Tag>
        return nested ? el : wrapBlock(el)
      }
    return {
      h1: renderAs('h1'),
      h2: renderAs('h2'),
      h3: renderAs('h3'),
      h4: renderAs('h4'),
      p: renderAs('p'),
      ul: renderAs('ul'),
      ol: renderAs('ol'),
      pre: renderAs('pre'),
      blockquote: renderAs('blockquote'),
      hr: renderAs('hr'),
      table: renderAs('table'),
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [comments, activeBlock])

  const total = countComments(comments)

  const handleSubmit = () => {
    onSubmit({ comments: collectSubmit(comments, bodyRef.current), summary })
  }

  return (
    <div className="rp">
      <div className="rp-header">
        <span className="rp-label">Review</span>
        <span className="rp-path">{path}</span>
        <span className="rp-spacer" />
        {isNew
          ? <span className="rp-badge-new">new</span>
          : <span className="rp-badge">{badgeLabel(total)}</span>}
      </div>

      <div className="rp-body" ref={bodyRef}>
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
          {content}
        </ReactMarkdown>
      </div>

      <div className="rp-footer">
        <div className="rp-footer-label">Overall feedback (optional)</div>
        <textarea
          className="rp-footer-ta"
          value={summary}
          onChange={e => setSummary(e.target.value)}
          placeholder="Summarize your review -- e.g. 'Looks good, just clarify the channel types and add PagerDuty'"
        />
        <div className="rp-footer-actions">
          <span className="rp-footer-hint">{hintFor(total)}</span>
          <span className="rp-spacer" />
          <Button variant="secondary" size="sm" onClick={onClose}>Close without submitting</Button>
          <Button variant="primary" size="sm" onClick={handleSubmit}>Submit review</Button>
        </div>
      </div>
    </div>
  )
}

export default ReviewPanel
