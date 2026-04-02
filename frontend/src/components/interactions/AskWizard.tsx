import { useState } from 'react'
import { useStore, AskQuestion } from '../../store/index'
import * as api from '../../api/client'
import { Md } from '../Md'

// Normalize raw question options from LLM output. Options may arrive as strings
// or dicts with varying key names. This is data cleaning for LLM output
// variability — not business logic.
function normalizeOptions(
  rawOpts: (string | Record<string, unknown>)[] | undefined,
): { value: string; label: string; recommended?: boolean }[] {
  if (!rawOpts) return []
  return rawOpts.map(o => {
    if (typeof o === 'string') return { value: o, label: o }
    const label = String(o['label'] ?? o['text'] ?? o['value'] ?? o['option'] ?? '')
    const value = String(o['value'] ?? o['label'] ?? o['text'] ?? label)
    return { value, label, recommended: (o['recommended'] as boolean) ?? false }
  })
}

/** True when the question should render as a free-form text input. */
function isFreeText(q: AskQuestion): boolean {
  return q.free_text === true || !q.options || q.options.length === 0
}

interface AnswerMap {
  [qIdx: number]: string | string[] | null
}

/** Map from question index to the "Other" free-text typed by the user. */
interface OtherTextMap {
  [qIdx: number]: string
}

function collectDefaults(questions: AskQuestion[]): AnswerMap {
  const defaults: AnswerMap = {}
  questions.forEach((q, i) => {
    if (isFreeText(q)) {
      defaults[i] = null
      return
    }
    const recommended = (q.options ?? []).filter(o => o.recommended).map(o => o.value)
    defaults[i] = q.multi ? recommended : (recommended[0] ?? null)
  })
  return defaults
}

function QuestionCard({
  question,
  qIdx,
  answer,
  otherText,
  onAnswer,
  onOtherText,
}: {
  question: AskQuestion
  qIdx: number
  answer: string | string[] | null
  otherText: string
  onAnswer: (qIdx: number, val: string | string[] | null) => void
  onOtherText: (qIdx: number, text: string) => void
}) {
  const selected = Array.isArray(answer) ? answer : answer ? [answer] : []

  const toggle = (value: string) => {
    if (value === '__other__') {
      if (question.multi) {
        const newSel = selected.includes('__other__')
          ? selected.filter(v => v !== '__other__')
          : [...selected, '__other__']
        onAnswer(qIdx, newSel)
      } else {
        onAnswer(qIdx, selected[0] === '__other__' ? null : '__other__')
      }
      return
    }
    if (question.multi) {
      const newSel = selected.includes(value)
        ? selected.filter(v => v !== value)
        : [...selected, value]
      onAnswer(qIdx, newSel)
    } else {
      onAnswer(qIdx, selected[0] === value ? null : value)
    }
  }

  // Normalize options at render time to handle LLM output variability.
  // Filter out any LLM-provided "Other" / meta-options — we always render our own.
  const isMetaOption = (s: string): boolean =>
    /^\(?[a-z]\)?\s*[.:\-)]?\s*/i.test(s) // strip letter prefixes like "(a) ", "A: "
      ? isMetaOption(s.replace(/^\(?[a-z]\)?\s*[.:\-)]?\s*/i, ''))
      : /^(other|none of the above|something else|other approach|other option|custom|n\/a)$/i.test(s.trim())
  const stripPrefix = (s: string) => s.replace(/^\(?[a-z]\)?\s*[.:\-)]?\s*/i, '').trim()
  const opts = normalizeOptions(question.options as (string | Record<string, unknown>)[])
    .filter(o => !isMetaOption(o.label))
    .map(o => ({ ...o, label: stripPrefix(o.label), value: stripPrefix(o.value) || o.value }))

  return (
    <div className="question-card">
      <div className="question-header">
        Question {qIdx + 1}
      </div>
      {question.context && (
        <div className="question-context"><Md>{question.context}</Md></div>
      )}
      <div className="question-text"><Md>{question.question}</Md></div>

      {isFreeText(question) ? (
        /* Free-form text input — no predefined options */
        <div className="free-text-area">
          <textarea
            className="free-text-input"
            rows={4}
            placeholder="Type your answer..."
            value={typeof answer === 'string' ? answer : ''}
            onChange={e => onAnswer(qIdx, e.target.value || null)}
          />
        </div>
      ) : (
        /* Standard option selection — always includes an "Other" text input */
        <>
          {question.multi && (
            <div className="question-multi-hint">Select all that apply</div>
          )}
          <div className="options-list">
            {opts.map(opt => (
              <div
                key={opt.value}
                className={`option${selected.includes(opt.value) ? ' selected' : ''}${opt.recommended ? ' recommended' : ''}`}
                onClick={() => toggle(opt.value)}
              >
                <span className={question.multi ? 'checkbox-dot' : 'radio-dot'} />
                <span className="option-text">{opt.label}</span>
                {opt.recommended && (
                  <span className="recommended-badge">recommended</span>
                )}
              </div>
            ))}
            <div
              className={`option option-other${selected.includes('__other__') ? ' selected' : ''}`}
              onClick={() => toggle('__other__')}
            >
              <span className={question.multi ? 'checkbox-dot' : 'radio-dot'} />
              <span className="option-text">Other (type your own)</span>
            </div>
            {selected.includes('__other__') && (
              <textarea
                className="free-text-input"
                rows={3}
                placeholder="Type your answer..."
                value={otherText}
                onChange={e => onOtherText(qIdx, e.target.value)}
              />
            )}
          </div>
        </>
      )}
    </div>
  )
}

/**
 * Resolve __other__ sentinels in the answer map with actual typed text.
 * For single-select: "__other__" → the typed string.
 * For multi-select: ["a", "__other__"] → ["a", "the typed string"].
 */
function resolveOtherText(
  answers: AnswerMap,
  otherTexts: OtherTextMap,
  questions: AskQuestion[],
): (string | string[] | null)[] {
  return questions.map((_, i) => {
    const raw = answers[i] ?? null
    const typed = otherTexts[i] || ''
    if (raw === '__other__') return typed || null
    if (Array.isArray(raw)) {
      return raw.map(v => (v === '__other__' ? typed : v))
    }
    return raw
  })
}

export function AskWizard() {
  const focus = useStore(s => s.run?.focus)
  const [currentIdx, setCurrentIdx] = useState(0)
  const [answers, setAnswers] = useState<AnswerMap>({})
  const [otherTexts, setOtherTexts] = useState<OtherTextMap>({})
  const [submitError, setSubmitError] = useState<string | null>(null)

  if (!focus || focus.type !== 'question') return null

  const { questions, token } = focus
  const total = questions.length

  const handleAnswer = (qIdx: number, val: string | string[] | null) => {
    setAnswers(prev => ({ ...prev, [qIdx]: val }))
  }

  const handleOtherText = (qIdx: number, text: string) => {
    setOtherTexts(prev => ({ ...prev, [qIdx]: text }))
  }

  const handleNext = () => {
    if (currentIdx < total - 1) setCurrentIdx(i => i + 1)
  }

  const handleBack = () => {
    if (currentIdx > 0) setCurrentIdx(i => i - 1)
  }

  const handleSubmit = async () => {
    const finalAnswers = resolveOtherText(answers, otherTexts, questions)
    const res = await api.submitAnswer(finalAnswers, token)
    if (!res.ok) {
      setSubmitError(res.message ?? 'Failed to submit answers')
    }
  }

  const handleUseDefaults = async () => {
    const defaults = collectDefaults(questions)
    const finalAnswers = questions.map((_, i) => defaults[i] ?? null)
    const res = await api.submitAnswer(finalAnswers, token)
    if (!res.ok) {
      setSubmitError(res.message ?? 'Failed to submit defaults')
    }
  }

  return (
    <div className="phase-content">
      <div className="phase-inner">
        <div className="count-progress">
          {currentIdx + 1} / {total}
        </div>

        <QuestionCard
          key={currentIdx}
          question={questions[currentIdx]}
          qIdx={currentIdx}
          answer={answers[currentIdx] ?? null}
          otherText={otherTexts[currentIdx] ?? ''}
          onAnswer={handleAnswer}
          onOtherText={handleOtherText}
        />

        {submitError && <div className="no-runners-msg">{submitError}</div>}

        <div className="form-actions">
          {currentIdx > 0 && (
            <button className="btn btn-secondary" onClick={handleBack}>
              Back
            </button>
          )}
          <button className="btn btn-secondary" onClick={handleUseDefaults}>
            Use Defaults
          </button>
          {currentIdx < total - 1 && (
            <button className="btn btn-primary" onClick={handleNext}>
              Next
            </button>
          )}
          {currentIdx === total - 1 && (
            <button
              id="btn-submit-answers"
              className="btn btn-primary"
              onClick={handleSubmit}
            >
              Submit
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
