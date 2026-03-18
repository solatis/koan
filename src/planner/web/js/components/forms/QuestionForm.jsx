import { useState } from 'preact/hooks'
import { useStore } from '../../store.js'
import { submitAnswers } from '../../lib/api.js'
import { QuestionCard } from './QuestionCard.jsx'

export function QuestionForm({ token }) {
  const { requestId, payload: questions } = useStore(s => s.pendingInput)
  const [selections, setSelections] = useState(() => new Array(questions.length).fill(null))

  const allAnswered = selections.every(s => s !== null && (s.selectedOptions?.length > 0 || s.customInput))
  const answeredCount = selections.filter(s => s !== null && (s.selectedOptions?.length > 0 || s.customInput)).length

  function updateSelection(index, selection) {
    setSelections(prev => {
      const next = [...prev]
      next[index] = selection
      return next
    })
  }

  function acceptDefaults() {
    const answers = questions.map((q) => {
      const idx = q.recommended ?? 0
      const label = q.options[idx]?.label
      return { questionId: q.id, selectedOptions: label ? [label] : [] }
    })
    submitAnswers({ token, requestId, answers })
  }

  function submit() {
    const answers = questions.map((q, i) => ({
      questionId: q.id,
      ...(selections[i] || { selectedOptions: [] }),
    }))
    submitAnswers({ token, requestId, answers })
  }

  return (
    <div class="phase-inner">
      <h2 class="phase-heading">A few questions to shape the plan</h2>
      <div class="count-progress">{answeredCount} of {questions.length} answered</div>

      {questions.map((q, i) => (
        <QuestionCard
          key={q.id}
          question={q}
          index={i}
          total={questions.length}
          onSelect={(sel) => updateSelection(i, sel)}
        />
      ))}

      <div class="form-actions">
        <button class="btn btn-secondary" onClick={acceptDefaults}>Accept All Defaults</button>
        <button class="btn btn-primary" disabled={!allAnswered} onClick={submit}>Submit Answers</button>
        {!allAnswered && <span class="form-helper">{questions.length - answeredCount} remaining</span>}
      </div>
    </div>
  )
}
