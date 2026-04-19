/**
 * ElicitationPanel — two-panel context/decision layout.
 * Supports single-select (radio), multi-select (checkbox), and free-text modes.
 * Supports multi-question pagination with Previous/Next.
 * Used in: elicitation interactions during workflow.
 */

import type { ReactNode } from 'react'
import { SectionLabel } from '../atoms/SectionLabel'
import { Button } from '../atoms/Button'
import { RadioOption } from '../molecules/RadioOption'
import { CheckboxOption } from '../molecules/CheckboxOption'
import './ElicitationPanel.css'

interface OptionEntry {
  label: string
  recommended?: boolean
  isCustom?: boolean
}

interface ElicitationPanelProps {
  context?: ReactNode
  question: string
  options: OptionEntry[]
  // Single-select mode (default)
  mode?: 'single-select' | 'multi-select' | 'free-text'
  selectedIndex?: number | null
  onSelect?: (index: number) => void
  // Multi-select mode
  selectedIndices?: number[]
  onToggle?: (index: number) => void
  // Free-text mode
  freeText?: string
  onFreeTextChange?: (text: string) => void
  // Custom "other" text (shared across modes)
  customText?: string
  onCustomTextChange?: (text: string) => void
  // Pagination
  questionNumber?: number
  totalQuestions?: number
  onPrevious?: () => void
  showPrevious?: boolean
  // Actions
  onSubmit: () => void
  onUseDefaults: () => void
  // Error
  error?: string | null
}

export function ElicitationPanel({
  context,
  question,
  options,
  mode = 'single-select',
  selectedIndex,
  onSelect,
  selectedIndices,
  onToggle,
  freeText,
  onFreeTextChange,
  customText,
  onCustomTextChange,
  questionNumber,
  totalQuestions,
  onPrevious,
  showPrevious,
  onSubmit,
  onUseDefaults,
  error,
}: ElicitationPanelProps) {
  const isLastQuestion = !totalQuestions || !questionNumber || questionNumber >= totalQuestions
  const submitLabel = isLastQuestion ? 'Submit' : 'Next'

  const renderOptions = () => {
    if (mode === 'free-text') {
      return (
        <textarea
          className="ep-free-text"
          rows={4}
          placeholder="Type your answer..."
          value={freeText ?? ''}
          onChange={e => onFreeTextChange?.(e.target.value)}
        />
      )
    }
    if (mode === 'multi-select') {
      return (
        <div className="ep-options">
          {options.map((opt, i) => (
            <CheckboxOption
              key={i}
              label={opt.label}
              selected={selectedIndices?.includes(i)}
              recommended={opt.recommended}
              isCustom={opt.isCustom}
              customText={opt.isCustom ? customText : undefined}
              onCustomTextChange={opt.isCustom ? onCustomTextChange : undefined}
              onClick={() => onToggle?.(i)}
            />
          ))}
        </div>
      )
    }
    // single-select (default)
    return (
      <div className="ep-options">
        {options.map((opt, i) => (
          <RadioOption
            key={i}
            label={opt.label}
            selected={selectedIndex === i}
            recommended={opt.recommended}
            isCustom={opt.isCustom}
            customText={opt.isCustom ? customText : undefined}
            onCustomTextChange={opt.isCustom ? onCustomTextChange : undefined}
            onClick={() => onSelect?.(i)}
          />
        ))}
      </div>
    )
  }

  return (
    <div className="ep">
      {totalQuestions && totalQuestions > 1 && questionNumber && (
        <div className="ep-counter">{questionNumber} / {totalQuestions}</div>
      )}
      <div className={context ? 'ep-grid' : 'ep-grid ep-grid--full'}>
        {context && (
          <div className="ep-panel ep-panel--context">
            <SectionLabel color="teal">Context</SectionLabel>
            <div className="ep-panel-body">{context}</div>
          </div>
        )}
        <div className="ep-panel ep-panel--decision">
          <SectionLabel color="orange">Decision</SectionLabel>
          <div className="ep-question">{question}</div>
          {mode === 'multi-select' && (
            <div className="ep-multi-hint">Select all that apply</div>
          )}
          {renderOptions()}
          {error && <div className="ep-error">{error}</div>}
          <div className="ep-actions">
            {showPrevious && <Button variant="secondary" onClick={onPrevious}>Previous</Button>}
            <Button variant="secondary" onClick={onUseDefaults}>Use Defaults</Button>
            <Button variant="primary" onClick={onSubmit}>{submitLabel}</Button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default ElicitationPanel
