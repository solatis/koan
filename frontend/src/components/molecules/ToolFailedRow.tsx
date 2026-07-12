/**
 * ToolFailedRow -- compact error row for a tool call whose arguments failed
 * validation (the fold replaced the in-flight entry with a ToolFailedEntry).
 *
 * The tool body never ran; pydantic-ai fed the validation error back to the
 * model, which retried. The row keeps that stumble visible as model-quality
 * signal. rawInput is the JSON-dumped last-known input -- an opaque string
 * rendered inside a collapsed disclosure, never interpreted as structure.
 *
 * Spec: docs/design-system.md -- Molecules -> ToolFailedRow.
 */

import './ToolFailedRow.css'

interface ToolFailedRowProps {
  toolName: string
  error: string
  rawInput?: string
}

export function ToolFailedRow({ toolName, error, rawInput }: ToolFailedRowProps) {
  return (
    <div className="tfr">
      <div className="tfr-header">
        <span className="tfr-x">x</span>
        <span className="tfr-label">Invalid call -- model retried</span>
        <span className="tfr-tool">{toolName}</span>
      </div>
      {error && <div className="tfr-error">{error}</div>}
      {rawInput && (
        <details className="tfr-raw">
          <summary className="tfr-raw-summary">raw input</summary>
          <pre className="tfr-raw-pre">{rawInput}</pre>
        </details>
      )}
    </div>
  )
}
