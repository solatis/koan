import { useState } from 'preact/hooks'

export function QuestionCard({ question, onSelect }) {
  const [selectedIndexes, setSelectedIndexes] = useState(() => new Set())
  const [otherInput, setOtherInput]           = useState('')

  const options    = question.options || []
  const allOptions = options.map(o => o.label)
  const otherIndex = allOptions.findIndex(l => l === 'Other (type your own)')
  const contextParagraphs = (question.context || '')
    .trim()
    .split(/\n\s*\n/g)
    .map(p => p.trim())
    .filter(Boolean)

  function buildSelection(indexes, otherVal) {
    if (question.multi) {
      const selectedOptions = []
      let customInput
      for (const idx of indexes) {
        if (idx === otherIndex) {
          const val = otherVal.trim()
          if (val) customInput = val
        } else {
          selectedOptions.push(allOptions[idx])
        }
      }
      return customInput !== undefined ? { selectedOptions, customInput } : { selectedOptions }
    } else {
      const idx = [...indexes][0]
      if (idx === otherIndex) {
        const val = otherVal.trim()
        return val ? { selectedOptions: [], customInput: val } : null
      }
      return { selectedOptions: [allOptions[idx]] }
    }
  }

  function handleSelect(i) {
    let next
    if (question.multi) {
      next = new Set(selectedIndexes)
      if (next.has(i)) next.delete(i)
      else next.add(i)
    } else {
      next = new Set([i])
    }
    setSelectedIndexes(next)
    onSelect(buildSelection(next, otherInput))
  }

  function handleOtherInput(e) {
    const val = e.target.value
    setOtherInput(val)
    if (selectedIndexes.has(otherIndex)) {
      onSelect(buildSelection(selectedIndexes, val))
    }
  }

  const showOtherInput = otherIndex !== -1 && selectedIndexes.has(otherIndex)

  return (
    <div class="question-card">
      <div class="question-header">{question.id}</div>
      {question.multi && <div class="question-multi-hint">select all that apply</div>}

      {contextParagraphs.length > 0 && (
        <div class="question-context">
          {contextParagraphs.map((p, i) => <p key={i}>{p}</p>)}
        </div>
      )}

      <div class="question-text">{question.question}</div>
      <div class="options-list">
        {allOptions.map((label, i) => {
          const isSelected    = selectedIndexes.has(i)
          const isRecommended = i === question.recommended && i !== otherIndex
          return (
            <div key={i} class={`option${i === otherIndex ? ' option-other' : ''}${isSelected ? ' selected' : ''}`} onClick={() => handleSelect(i)}>
              <span class={question.multi ? 'checkbox-dot' : 'radio-dot'} />
              <span class="option-text">{label}</span>
              {isRecommended && <span class="recommended-badge">recommended</span>}
            </div>
          )
        })}
        <input
          class={`other-input${showOtherInput ? ' visible' : ''}`}
          type="text"
          placeholder="Type your answer..."
          value={otherInput}
          onInput={handleOtherInput}
        />
      </div>
    </div>
  )
}
