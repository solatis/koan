/**
 * KoanToolCard -- rich card for koan MCP tool calls in the content stream.
 *
 * Dispatches to tool-specific render functions by toolName via the
 * TOOL_RENDERERS map. Each renderer receives typed props including toolInput
 * (the M1 aggregate field) for live partial-args rendering. Unrecognized
 * tools fall back to a labeled header-only card via FallbackCard. Suppressed
 * orchestration tools (koan_set_phase, koan_suggest_next) return null.
 * koan_complete_step was removed in M6.
 *
 * Wrapped in React.memo: re-renders only when its props change. Because it
 * lives inside an EntryRow (itself memo'd by entry reference), re-renders
 * during token streaming that do not touch this entry's ToolKoanEntry are
 * suppressed at the EntryRow boundary.
 *
 * Used in: content stream, replacing ToolCallRow for koan MCP tool entries.
 */

import React, { type ReactElement } from 'react'
import './KoanToolCard.css'
import { Md } from '../Md'

interface KoanToolCardProps {
  toolName: string
  args: Record<string, unknown>
  // toolInput is the canonical field to bind to for live rendering; it is the
  // M1 fold's aggregate of all received tool_input_delta chunks. Prefer this
  // over args for partial-args display -- M3 may diverge the two fields.
  toolInput: Record<string, unknown> | null
  result: Record<string, unknown> | null
  inFlight: boolean
}

// ToolRenderer is the contract for first-class per-tool renderers registered
// in TOOL_RENDERERS. FallbackCard is NOT a ToolRenderer -- it takes its own
// {label, inFlight} shape and is invoked directly by the dispatch else-branch.
type ToolRenderer = (props: Omit<KoanToolCardProps, 'toolName'>) => ReactElement

// Orchestration tools whose effects are visible through other molecules
// (StepHeader, PhaseMarker, YieldPanel). They are suppressed at the koan-tool
// dispatch -- the entry exists in the projection (ToolKoanEntry) but does not
// render in the activity feed.
// koan_complete_step removed in M6; koan_suggest_next added (M6).
const SUPPRESSED_TOOLS = new Set(['koan_set_phase', 'koan_suggest_next'])

// Human-readable labels for the FallbackCard header. Tools not present here
// render their raw toolName as the label.
const KOAN_TOOL_LABELS: Record<string, string> = {
  koan_request_scouts: 'Dispatching scouts',
  koan_request_executor: 'Starting executor',
  koan_artifact_list: 'Listing artifacts',
  koan_artifact_read: 'Reading artifact',
  koan_memorize: 'Recording memory',
  koan_forget: 'Forgetting memory entry',
  koan_memory_status: 'Reading memory status',
  koan_search: 'Searching memory',
  // koan_memory_propose label removed in M7: tool retired.
}

// -- Shared SVG --------------------------------------------------------------

function CheckSvg() {
  return (
    <svg className="ktc-check" viewBox="0 0 14 14" fill="none" aria-hidden="true">
      <path d="M2.5 7.5L5.5 10.5L11.5 4" stroke="var(--color-teal)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

// -- Tool renderers -----------------------------------------------------------

// ReflectCard reads toolInput (not args) for question/context per M3 split-source
// design: streaming args come via tool_input_delta -> toolInput; the result
// accumulates via reflect_delta domain events and is overwritten by the final
// tool_result payload. Both fields are on the same entry; no args needed.
function ReflectCard({ toolInput, result, inFlight }: Omit<KoanToolCardProps, 'toolName'>) {
  const question = (toolInput?.question as string) || ''
  const context = (toolInput?.context as string) || ''
  const answer = result?.answer as string | undefined
  const citations = (result?.citations as { id: string; title: string }[]) || []
  const iterations = result?.iterations as number | undefined

  return (
    <div className="ktc ktc--reflect">
      <div className="ktc-header">
        <span className="ktc-indicator">
          {inFlight ? <span className="ktc-running-dot" /> : <CheckSvg />}
        </span>
        <span className="ktc-label">Reflecting</span>
        {iterations != null && (
          <span className="ktc-meta">{iterations} search{iterations === 1 ? '' : 'es'}</span>
        )}
      </div>
      <div className="ktc-question">{question}</div>
      {context && <div className="ktc-context">{context}</div>}
      {answer && (
        <div className="ktc-answer">
          <Md>{answer}</Md>
          {citations.length > 0 && (
            <div className="ktc-citations">
              {citations.map((c, i) => (
                <span key={i} className="ktc-cite">{c.title}</span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ArtifactWriteCard shows a live preview of the artifact content as the LLM
// streams args. While inFlight, content is rendered as plain pre-wrapped text
// to avoid the O(n^2) markdown re-parse cost of growing content on each token
// delta. Once complete (not inFlight), the content is rendered via <Md> for
// full formatting. Reads toolInput (aggregate) so every delta tick updates the
// preview. Args: filename, content per koan_artifact_write signature.
// Status display removed -- artifact lifecycle state is no longer tracked in frontmatter.
function ArtifactWriteCard({ toolInput, inFlight }: Omit<KoanToolCardProps, 'toolName'>) {
  const filename = (toolInput?.filename as string) || ''
  const content = (toolInput?.content as string) || ''
  return (
    <div className="ktc ktc--artifact-write">
      <div className="ktc-header">
        <span className="ktc-indicator">
          {inFlight ? <span className="ktc-running-dot" /> : <CheckSvg />}
        </span>
        <span className="ktc-label">
          {inFlight ? 'Writing artifact' : 'Wrote artifact'}
        </span>
        {filename && <span className="ktc-meta">{filename}</span>}
      </div>
      {content && (
        <div className="ktc-artifact-preview">
          {inFlight
            ? <pre className="ktc-artifact-streaming">{content}</pre>
            : <Md>{content}</Md>
          }
        </div>
      )}
    </div>
  )
}

/**
 * ArtifactEditCard renders a koan_artifact_edit call showing the filename only.
 * old_string/new_string are not shown -- the filename is sufficient context for
 * the activity feed (brief.md decision 7).
 */
function ArtifactEditCard({ toolInput, inFlight }: Omit<KoanToolCardProps, 'toolName'>) {
  const filename = (toolInput?.filename as string) || ''
  return (
    <div className="ktc ktc--artifact-edit">
      <div className="ktc-header">
        <span className="ktc-indicator">
          {inFlight ? <span className="ktc-running-dot" /> : <CheckSvg />}
        </span>
        <span className="ktc-label">
          {inFlight ? 'Editing artifact' : 'Edited artifact'}
        </span>
        {filename && <span className="ktc-meta">{filename}</span>}
      </div>
    </div>
  )
}

// YieldCard stays in_flight=True for the entire user-block window per intake
// decision 8 -- the pulsing dot signals "awaiting user". Suggestions are shown
// to give context about what the orchestrator is offering.
function YieldCard({ toolInput, inFlight }: Omit<KoanToolCardProps, 'toolName'>) {
  const suggestions =
    (toolInput?.suggestions as { label?: string }[] | undefined) ?? []
  return (
    <div className="ktc ktc--yield">
      <div className="ktc-header">
        <span className="ktc-indicator">
          {inFlight ? <span className="ktc-running-dot" /> : <CheckSvg />}
        </span>
        <span className="ktc-label">
          {inFlight ? 'Yielded -- awaiting user' : 'Yielded'}
        </span>
      </div>
      {suggestions.length > 0 && (
        <ul className="ktc-suggestions">
          {suggestions.map((s, i) => (
            <li key={i} className="ktc-suggestion">{s.label || ''}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

// AskQuestionCard stays in_flight=True for the full user-wait window (same
// rationale as YieldCard). Questions are listed so the user can see what is
// being asked while the orchestrator blocks.
function AskQuestionCard({ toolInput, inFlight }: Omit<KoanToolCardProps, 'toolName'>) {
  const questions =
    (toolInput?.questions as { question?: string }[] | undefined) ?? []
  return (
    <div className="ktc ktc--ask">
      <div className="ktc-header">
        <span className="ktc-indicator">
          {inFlight ? <span className="ktc-running-dot" /> : <CheckSvg />}
        </span>
        <span className="ktc-label">
          {inFlight ? 'Asking question -- awaiting user' : 'Question answered'}
        </span>
        {questions.length > 1 && (
          <span className="ktc-meta">{questions.length} questions</span>
        )}
      </div>
      {questions.length > 0 && (
        <ul className="ktc-questions">
          {questions.map((q, i) => (
            <li key={i} className="ktc-question-item">{q.question || ''}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ExecutorCard renders one koan_request_executor call. Each call has its own
// ToolKoanEntry (correlated by call_id), so concurrent executors render as
// independent cards. The executor's terminal error -- the failing agent's last
// message before exit -- arrives in this entry's result and is shown inline,
// replacing the prior toast-notification path.
function ExecutorCard({ toolInput, result, inFlight }: Omit<KoanToolCardProps, 'toolName'>) {
  const artifacts = (toolInput?.artifacts as string[] | undefined) ?? []
  const status = (result?.status as string | undefined) ?? null
  const failed = status === 'failed'
  const errorText = (result?.error as string | undefined) ?? ''
  const exitCode = result?.exit_code as number | undefined
  const label = inFlight ? 'Running executor' : failed ? 'Executor failed' : 'Executor done'
  return (
    <div className={`ktc ktc--executor${failed ? ' ktc--executor-failed' : ''}`}>
      <div className="ktc-header">
        <span className="ktc-indicator">
          {inFlight ? <span className="ktc-running-dot" /> : <CheckSvg />}
        </span>
        <span className="ktc-label">{label}</span>
        {artifacts.length > 0 && (
          <span className="ktc-meta">{artifacts.length} artifact{artifacts.length === 1 ? '' : 's'}</span>
        )}
      </div>
      {failed && (
        <div className="ktc-executor-error">
          {exitCode != null && <div className="ktc-executor-error-meta">exit {exitCode}</div>}
          {errorText && <Md>{errorText}</Md>}
        </div>
      )}
    </div>
  )
}

// FallbackCard is NOT in TOOL_RENDERERS -- it takes its own clean prop shape
// and is invoked directly by the dispatch else-branch. This avoids threading
// a label through the ToolRenderer signature.
function FallbackCard({ label, inFlight }: { label: string; inFlight: boolean }) {
  return (
    <div className="ktc ktc--fallback">
      <div className="ktc-header">
        <span className="ktc-indicator">
          {inFlight ? <span className="ktc-running-dot" /> : <CheckSvg />}
        </span>
        <span className="ktc-label">{label}</span>
      </div>
    </div>
  )
}

// -- Dispatch -----------------------------------------------------------------

// Only first-class renderers go here. FallbackCard is invoked by the
// else-branch below and is intentionally absent from this map.
const TOOL_RENDERERS: Record<string, ToolRenderer> = {
  koan_reflect: ReflectCard,
  koan_artifact_write: ArtifactWriteCard,
  koan_artifact_edit: ArtifactEditCard,
  koan_yield: YieldCard,
  koan_ask_question: AskQuestionCard,
  koan_request_executor: ExecutorCard,
}

export const KoanToolCard = React.memo(function KoanToolCard(props: KoanToolCardProps): ReactElement | null {
  if (SUPPRESSED_TOOLS.has(props.toolName)) {
    return null
  }
  const Renderer = TOOL_RENDERERS[props.toolName]
  if (Renderer) {
    return (
      <Renderer
        args={props.args}
        toolInput={props.toolInput}
        result={props.result}
        inFlight={props.inFlight}
      />
    )
  }
  const label = KOAN_TOOL_LABELS[props.toolName] ?? props.toolName
  return <FallbackCard label={label} inFlight={props.inFlight} />
})

export default KoanToolCard
