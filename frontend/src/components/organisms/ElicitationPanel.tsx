/**
 * ElicitationPanel — two-panel context/decision layout.
 * Supports single-select (radio), multi-select (checkbox), and free-text modes.
 * Supports multi-question pagination with Previous/Next.
 * Ctrl/Cmd+Return inside any textarea (the free-text field or an "other"
 * option field) submits the current answer and advances to the next question,
 * or finalizes if this is the last question.
 * Used in: elicitation interactions during workflow.
 */

import type { KeyboardEvent, ReactNode } from 'react'
import { useFileAttachment } from '../../hooks/useFileAttachment'
import { SectionLabel } from '../atoms/SectionLabel'
import { Button } from '../atoms/Button'
import { FileChip } from '../atoms/FileChip'
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
  onSubmit: (attachments?: string[]) => void
  onUseDefaults: () => void
  // Error
  error?: string | null
}

const PaperclipIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.49" />
  </svg>
)

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
  const attach = useFileAttachment()

  const handleSubmit = () => {
    const ids = attach.fileIds.length > 0 ? attach.fileIds : undefined
    onSubmit(ids)
  }

  /**
   * Delegated keyboard handler for the decision panel.
   *
   * Fires Ctrl/Cmd+Return only when the event originates from a <textarea>
   * (the free-text field or an "other" option field), satisfying the
   * "text fields only" scope. Plain Enter is left untouched so the textarea
   * can insert newlines. preventDefault() suppresses the newline that the
   * submitting keystroke would otherwise add before the panel advances.
   *
   * Delegation keeps RadioOption and CheckboxOption purely presentational --
   * no submit-chord prop is threaded into the molecule contracts.
   */
  const handleDecisionKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (
      e.key === 'Enter' &&
      (e.ctrlKey || e.metaKey) &&
      (e.target as HTMLElement).tagName === 'TEXTAREA'
    ) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const renderOptions = () => {
    if (mode === 'free-text') {
      return (
        <>
          <div className="ep-free-text-wrap" {...attach.dragProps}>
            <textarea
              className="ep-free-text"
              rows={4}
              placeholder="Type your answer..."
              value={freeText ?? ''}
              onChange={e => onFreeTextChange?.(e.target.value)}
              onPaste={attach.onPaste}
            />
            <button className="ep-attach-btn" onClick={attach.openPicker} title="Attach files" type="button">
              <PaperclipIcon />
            </button>
            <input ref={attach.inputRef} type="file" multiple className="ep-file-input" onChange={attach.onInputChange} tabIndex={-1} />
          </div>
          {attach.files.length > 0 && (
            <div className="ep-chips">
              {attach.files.map(f => (
                <FileChip key={f.id} name={f.name} size={f.size} state={f.state} onRemove={() => attach.removeFile(f.id)} />
              ))}
            </div>
          )}
        </>
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
        <div className="ep-panel ep-panel--decision" onKeyDown={handleDecisionKeyDown}>
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
            <Button variant="primary" onClick={handleSubmit}>{submitLabel}</Button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default ElicitationPanel
