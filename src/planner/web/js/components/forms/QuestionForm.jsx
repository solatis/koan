import { useState } from 'preact/hooks'
import { useStore } from '../../store.js'
import { submitAnswers } from '../../lib/api.js'
import { QuestionCard } from './QuestionCard.jsx'

export function QuestionForm({ token }) {
  const { requestId, payload: question } = useStore(s => s.pendingInput)
  const [selection, setSelection] = useState(null)

  const answered = selection !== null && (selection.selectedOptions?.length > 0 || selection.customInput)

  function acceptDefault() {
    const idx = question.recommended ?? 0
    const label = question.options[idx]?.label
    const answer = {
      questionId: question.id,
      selectedOptions: label ? [label] : [],
    }
    submitAnswers({ token, requestId, answer })
  }

  function submit() {
    const answer = {
      questionId: question.id,
      ...(selection || { selectedOptions: [] }),
    }
    submitAnswers({ token, requestId, answer })
  }

  return (
    <div class="phase-inner">
      <h2 class="phase-heading">A question to shape the plan</h2>

      <QuestionCard
        question={question}
        onSelect={setSelection}
      />

      <div class="form-actions">
        <button class="btn btn-secondary" onClick={acceptDefault}>Use Default</button>
        <button class="btn btn-primary" disabled={!answered} onClick={submit}>Submit Answer</button>
        {!answered && <span class="form-helper">Choose an option or provide custom input</span>}
      </div>
    </div>
  )
}
