/**
 * ModelPicker — combobox for choosing a model id for a connection.
 *
 * Not the Select atom: it filters, groups ("newest in family" pins above the
 * flat list), accepts free-text ids, shows a loading state, and degrades to
 * free-text + catalog for non-listing providers (bedrock, voyage).
 * Presentational: the parent owns fetching; this owns open/close, filter,
 * highlight, and commit.
 *
 * The listing-capable "All models" list is capped to MAX_VISIBLE_ROWS rows.
 * When the filtered set exceeds the cap, a non-interactive hint shows the
 * total count and prompts the user to refine the filter to see more. This
 * keeps the mounted DOM bounded for large provider lists (e.g. openrouter's
 * ~600 models) without adding a virtualization dependency.
 */

import './ModelPicker.css'
import { useEffect, useRef, useState } from 'react'

export interface ModelPickerProps {
  connectionId: string | null // display only ("Loading models from {id}…")
  value: string | null
  onChange: (modelId: string) => void
  models: string[] // flat list, already ordered
  families?: { family: string; resolved: string }[] // pin group; listing-capable only
  loading?: boolean
  listingCapable: boolean
  catalogSuggestions?: string[] // non-listing only
  /** When false, the free-text input is suppressed in all branches (listing, loading,
   *  non-listing).  Used for voyage embedding models where the model set is a fixed
   *  whitelist; free-text entry would produce a backend 422. Default: true. */
  allowFreeText?: boolean
  disabled?: boolean
}

// Cap the number of "All models" rows actually mounted so the DOM stays
// bounded for large provider lists (e.g. openrouter ~600 models). Users reach
// models beyond the cap by refining the filter. No virtualization dep needed.
const MAX_VISIBLE_ROWS = 50

const rowClass = (selected: boolean, highlighted: boolean, extra?: string) =>
  [
    'mol-model-picker__row',
    selected && 'is-selected',
    highlighted && 'is-highlighted',
    extra,
  ]
    .filter(Boolean)
    .join(' ')

export function ModelPicker({
  connectionId,
  value,
  onChange,
  models,
  families,
  loading = false,
  listingCapable,
  catalogSuggestions,
  allowFreeText = true,
  disabled = false,
}: ModelPickerProps) {
  const [open, setOpen] = useState(false)
  const [filter, setFilter] = useState('')
  const [freeText, setFreeText] = useState('')
  const [highlight, setHighlight] = useState(-1) // index into navCommits; -1 = unset

  const rootRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const filterInputRef = useRef<HTMLInputElement>(null)
  const freeTextRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  // --- derived view model ---
  const fams = families ?? []
  const filterNorm = filter.trim().toLowerCase()
  const showPins = listingCapable && !loading && fams.length > 0 && filter.trim() === ''
  const filteredModels = models.filter(m => m.toLowerCase().includes(filterNorm))
  // Slice filteredModels to keep the mounted DOM bounded. Both navCommits and
  // the render map use this same slice so data-nav-index stays in sync with
  // the keyboard highlight (the render-order == navCommits invariant).
  const visibleModels = filteredModels.slice(0, MAX_VISIBLE_ROWS)
  const overflowCount = filteredModels.length - visibleModels.length
  const suggestions = catalogSuggestions ?? []
  const conn = connectionId ?? 'connection'

  // The ordered list of selectable commits the keyboard highlight walks. Render
  // order must match this so data-nav-index lines up with the highlight index.
  // In the listing-capable branch the "All models" rows are capped to
  // visibleModels (same slice used by the render map) so the nav indices
  // stay aligned with mounted rows even when the full list is truncated.
  const navCommits: string[] = loading
    ? []
    : listingCapable
      ? [...(showPins ? fams.map(f => f.resolved) : []), ...visibleModels]
      : suggestions
  const pinCount = showPins ? fams.length : 0

  // --- commit / close ---
  const focusTrigger = () => requestAnimationFrame(() => triggerRef.current?.focus())

  const commit = (id: string) => {
    onChange(id)
    setOpen(false)
    setFilter('')
    setFreeText('')
    setHighlight(-1)
    focusTrigger()
  }

  const close = () => {
    setOpen(false)
    setHighlight(-1)
    focusTrigger()
  }

  // --- effects ---
  // Outside mousedown closes.
  useEffect(() => {
    if (!open) return
    const onDocMouseDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDocMouseDown)
    return () => document.removeEventListener('mousedown', onDocMouseDown)
  }, [open])

  // On open, focus the filter input (listing) or the free-text input (loading /
  // non-listing).
  useEffect(() => {
    if (!open) return
    const target = listingCapable && !loading ? filterInputRef.current : freeTextRef.current
    target?.focus()
  }, [open, listingCapable, loading])

  // Keep the highlighted row scrolled into view.
  useEffect(() => {
    if (highlight < 0) return
    const el = listRef.current?.querySelector(`[data-nav-index="${highlight}"]`)
    if (el) (el as HTMLElement).scrollIntoView({ block: 'nearest' })
  }, [highlight])

  // --- keyboard ---
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (disabled) return
    if (!open) {
      // Enter / Space open via the button's native click; only ArrowDown needs
      // explicit handling to open.
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setOpen(true)
      }
      return
    }
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault()
        setHighlight(h => (navCommits.length === 0 ? -1 : h < 0 ? 0 : Math.min(h + 1, navCommits.length - 1)))
        break
      case 'ArrowUp':
        e.preventDefault()
        setHighlight(h => (navCommits.length === 0 ? -1 : h < 0 ? 0 : Math.max(h - 1, 0)))
        break
      case 'Enter':
        if (highlight >= 0 && highlight < navCommits.length) {
          e.preventDefault()
          commit(navCommits[highlight])
        } else if (allowFreeText && e.target === freeTextRef.current && freeText.trim()) {
          e.preventDefault()
          commit(freeText.trim())
        }
        break
      case 'Escape':
        e.preventDefault()
        close()
        break
      case 'Tab':
        // Tab past the last focusable element (the free-text input) closes the
        // panel; focus proceeds naturally.
        if (!e.shiftKey && e.target === freeTextRef.current) setOpen(false)
        break
    }
  }

  // --- row renderer ---
  const Row = (id: string, navIndex: number, extra?: string, children?: React.ReactNode) => (
    <div
      key={`${extra ?? 'row'}-${id}`}
      role="option"
      aria-selected={value === id}
      data-nav-index={navIndex}
      className={rowClass(value === id, highlight === navIndex, extra)}
      onMouseDown={e => e.preventDefault()} // keep input focus; avoid blur/click race
      onClick={() => commit(id)}
    >
      {children ?? id}
    </div>
  )

  const freeTextInput = (label: string, top: boolean) => (
    <div className={`mol-model-picker__freetext${top ? ' mol-model-picker__freetext--top' : ''}`}>
      <div className="mol-model-picker__sublabel">{label}</div>
      <input
        ref={freeTextRef}
        type="text"
        className="mol-model-picker__freetext-input"
        value={freeText}
        placeholder="e.g. claude-opus-4"
        onChange={e => setFreeText(e.target.value)}
      />
    </div>
  )

  const triggerCls = [
    'mol-model-picker__trigger',
    open && 'is-open',
    disabled && 'is-disabled',
    !value && 'is-placeholder',
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <div className="mol-model-picker" ref={rootRef} onKeyDown={onKeyDown}>
      <button
        type="button"
        ref={triggerRef}
        className={triggerCls}
        disabled={disabled}
        role="combobox"
        aria-expanded={open}
        aria-haspopup="listbox"
        onClick={() => setOpen(o => !o)}
      >
        {value ?? <span className="mol-model-picker__placeholder">— pick a model —</span>}
      </button>

      {open && !disabled && (
        <div className="mol-model-picker__panel">
          {loading ? (
            // B. LOADING
            <>
              <div className="mol-model-picker__loading">
                <div className="mol-model-picker__loading-row">
                  <span className="mol-model-picker__spinner" aria-hidden="true" />
                  <span>Loading models from {conn}...</span>
                </div>
                <div className="mol-model-picker__skeleton" style={{ width: '60%' }} />
                <div className="mol-model-picker__skeleton" style={{ width: '72%' }} />
                <div className="mol-model-picker__skeleton" style={{ width: '54%' }} />
              </div>
              {allowFreeText && freeTextInput('Or enter a model id', false)}
            </>
          ) : !listingCapable ? (
            // C. NON-LISTING
            <>
              {allowFreeText && freeTextInput('Model id', true)}
              {suggestions.length > 0 && (
                <div className="mol-model-picker__list" role="listbox" ref={listRef}>
                  <div className="mol-model-picker__grouplabel">Suggestions · koan catalog</div>
                  {suggestions.map((s, i) => Row(s, i))}
                </div>
              )}
              {allowFreeText && (
                <div className="mol-model-picker__note">
                  This provider can't list models over its API -- enter the id or pick from koan's
                  catalog.
                </div>
              )}
            </>
          ) : (
            // A. LISTING-CAPABLE
            <>
              <div className="mol-model-picker__filter">
                <svg
                  className="mol-model-picker__search"
                  viewBox="0 0 24 24"
                  fill="none"
                  aria-hidden="true"
                >
                  <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="2" />
                  <path d="M21 21l-4.3-4.3" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                </svg>
                <input
                  ref={filterInputRef}
                  type="text"
                  className="mol-model-picker__filter-input"
                  value={filter}
                  placeholder="Filter models"
                  onChange={e => {
                    setFilter(e.target.value)
                    setHighlight(-1)
                  }}
                />
              </div>

              <div className="mol-model-picker__list" role="listbox" ref={listRef}>
                {showPins && (
                  <>
                    <div className="mol-model-picker__grouplabel">Newest in family · pins a version</div>
                    {fams.map((f, i) =>
                      Row(f.resolved, i, 'mol-model-picker__row--pin', (
                        <>
                          <span className="mol-model-picker__pin-family">{f.family}</span>
                          <span className="mol-model-picker__pin-resolved">-&gt; {f.resolved}</span>
                        </>
                      )),
                    )}
                  </>
                )}

                <div className="mol-model-picker__grouplabel">All models · {conn}</div>
                {filteredModels.length === 0 ? (
                  <div className="mol-model-picker__nomatch">No models match</div>
                ) : (
                  visibleModels.map((m, i) => Row(m, pinCount + i))
                )}
                {overflowCount > 0 && (
                  <div className="mol-model-picker__more-hint">
                    Showing {visibleModels.length} of {filteredModels.length} -- refine your filter to see more
                  </div>
                )}
              </div>

              {allowFreeText && freeTextInput('Or enter a model id', false)}
            </>
          )}
        </div>
      )}
    </div>
  )
}

export default ModelPicker
