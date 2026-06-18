/**
 * ElicitationView -- store connector + interaction handler for the question
 * elicitation flow.  Reads the current focus via selectFocus (narrow selector)
 * and renders ElicitationPanel when the focus is a question batch.
 *
 * Fully replaces AskWizard.  All local state (currentIdx, answers, otherTexts,
 * attachmentsByIdx, submitError) is scoped to a single question session and
 * resets when the focus changes.
 *
 * Moved from App.tsx to this module in M5.
 */

import { useState } from 'react'
import { useStore, type AskQuestion } from '../../store/index'
import { selectFocus } from '../../store/selectors'
import { normalizeOptions } from '../../utils'
import * as api from '../../api/client'
import { ElicitationPanel } from './ElicitationPanel'
import { Md } from '../Md'

// ---------------------------------------------------------------------------
// isFreeText helper
// ---------------------------------------------------------------------------

function isFreeText(q: AskQuestion): boolean {
  return q.free_text === true || !q.options || q.options.length === 0
}

// ---------------------------------------------------------------------------
// ElicitationView
// ---------------------------------------------------------------------------

export function ElicitationView() {
  const focus = useStore(selectFocus)
  const [currentIdx, setCurrentIdx] = useState(0)
  const [answers, setAnswers] = useState<Record<number, string | string[] | null>>({})
  const [otherTexts, setOtherTexts] = useState<Record<number, string>>({})
  // Per-question attachment IDs; collected as the user pages through questions
  // and folded into the final answer list on submit per M3 wire shape.
  const [attachmentsByIdx, setAttachmentsByIdx] = useState<Record<number, string[]>>({})
  const [submitError, setSubmitError] = useState<string | null>(null)

  if (!focus || focus.type !== 'question') return null
  const { questions, token } = focus
  const total = questions.length
  const q = questions[currentIdx]
  const opts = normalizeOptions(q.options as (string | Record<string, unknown>)[])
  const freeText = isFreeText(q)
  const multi = q.multi

  const optionEntries = [
    ...opts.map(o => ({ label: o.label, recommended: o.recommended })),
    ...(!freeText ? [{ label: 'Other (type your own)', isCustom: true }] : []),
  ]

  const answer = answers[currentIdx] ?? null
  const selected = Array.isArray(answer) ? answer : answer ? [answer] : []

  const selectedIndex = (!multi && !freeText)
    ? (() => {
        const idx = optionEntries.findIndex((_, i) => {
          if (i < opts.length) return selected.includes(opts[i].value)
          return selected.includes('__other__')
        })
        return idx >= 0 ? idx : null
      })()
    : null

  const selectedIndices = multi
    ? optionEntries.map((_, i) => {
        const val = i < opts.length ? opts[i].value : '__other__'
        return selected.includes(val) ? i : -1
      }).filter(i => i >= 0)
    : []

  const handleSelect = (idx: number) => {
    const val = idx < opts.length ? opts[idx].value : '__other__'
    setAnswers(prev => ({ ...prev, [currentIdx]: selected[0] === val ? null : val }))
  }

  const handleToggle = (idx: number) => {
    const val = idx < opts.length ? opts[idx].value : '__other__'
    const newSel = selected.includes(val) ? selected.filter(v => v !== val) : [...selected, val]
    setAnswers(prev => ({ ...prev, [currentIdx]: newSel }))
  }

  const handleFreeTextChange = (text: string) => {
    setAnswers(prev => ({ ...prev, [currentIdx]: text || null }))
  }

  const handleCustomTextChange = (text: string) => {
    setOtherTexts(prev => ({ ...prev, [currentIdx]: text }))
  }

  const resolveAnswers = () => {
    return questions.map((_, i) => {
      const raw = answers[i] ?? null
      const typed = otherTexts[i] || ''
      if (raw === '__other__') return typed || null
      if (Array.isArray(raw)) return raw.map(v => v === '__other__' ? typed : v)
      return raw
    })
  }

  const handleSubmit = async (attachments?: string[]) => {
    // Record attachments for the current question before advancing or submitting.
    if (attachments && attachments.length > 0) {
      setAttachmentsByIdx(prev => ({ ...prev, [currentIdx]: attachments }))
    }
    if (currentIdx < total - 1) { setCurrentIdx(i => i + 1); return }
    // Wrap each resolved answer as {answer, attachments?} per M3 wire shape.
    // Use the just-received attachments for the final question rather than
    // the stale state entry (state update is async).
    const final = resolveAnswers().map((ans, i) => {
      const a = i === currentIdx ? attachments : attachmentsByIdx[i]
      if (a && a.length > 0) return { answer: ans, attachments: a }
      return { answer: ans }
    })
    const res = await api.submitAnswer(final, token)
    if (!res.ok) setSubmitError(res.message ?? 'Failed to submit answers')
  }

  const handleUseDefaults = async () => {
    const defaults = questions.map(qq => {
      if (isFreeText(qq)) return null
      const rec = (qq.options ?? []).filter(o => o.recommended).map(o => o.value)
      return qq.multi ? rec : (rec[0] ?? null)
    })
    const res = await api.submitAnswer(defaults, token)
    if (!res.ok) setSubmitError(res.message ?? 'Failed to submit defaults')
  }

  const mode = freeText ? 'free-text' : multi ? 'multi-select' : 'single-select'

  return (
    <ElicitationPanel
      context={q.context ? <Md>{q.context}</Md> : undefined}
      question={q.question}
      options={optionEntries}
      mode={mode as 'single-select' | 'multi-select' | 'free-text'}
      selectedIndex={selectedIndex}
      onSelect={handleSelect}
      selectedIndices={selectedIndices}
      onToggle={handleToggle}
      freeText={freeText ? (typeof answer === 'string' ? answer : '') : undefined}
      onFreeTextChange={freeText ? handleFreeTextChange : undefined}
      customText={otherTexts[currentIdx] ?? ''}
      onCustomTextChange={handleCustomTextChange}
      questionNumber={currentIdx + 1}
      totalQuestions={total}
      showPrevious={currentIdx > 0}
      onPrevious={() => setCurrentIdx(i => i - 1)}
      onSubmit={handleSubmit}
      onUseDefaults={handleUseDefaults}
      error={submitError}
    />
  )
}
