/**
 * KoanToolCard -- rich card for koan MCP tool calls in the content stream.
 *
 * Dispatches to tool-specific render functions by toolName via the
 * TOOL_RENDERERS map. Each renderer receives typed args and optional
 * result. Unrecognized tools fall back to a minimal header-only card.
 *
 * Used in: content stream, replacing ToolCallRow for renderable koan tools.
 */

import type { ReactElement } from 'react'
import './KoanToolCard.css'
import { Md } from '../Md'

interface KoanToolCardProps {
  toolName: string
  args: Record<string, unknown>
  result: Record<string, unknown> | null
  inFlight: boolean
}

type ToolRenderer = (props: Omit<KoanToolCardProps, 'toolName'>) => ReactElement

// -- Shared SVG --------------------------------------------------------------

function CheckSvg() {
  return (
    <svg className="ktc-check" viewBox="0 0 14 14" fill="none" aria-hidden="true">
      <path d="M2.5 7.5L5.5 10.5L11.5 4" stroke="var(--color-teal)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

// -- Tool renderers -----------------------------------------------------------

function ReflectCard({ args, result, inFlight }: Omit<KoanToolCardProps, 'toolName'>) {
  const question = (args.question as string) || ''
  const context = (args.context as string) || ''
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

function FallbackCard({ inFlight }: Omit<KoanToolCardProps, 'toolName'>) {
  return (
    <div className="ktc">
      <div className="ktc-header">
        <span className="ktc-indicator">
          {inFlight ? <span className="ktc-running-dot" /> : <CheckSvg />}
        </span>
        <span className="ktc-label">koan tool</span>
      </div>
    </div>
  )
}

// -- Dispatch -----------------------------------------------------------------

const TOOL_RENDERERS: Record<string, ToolRenderer> = {
  koan_reflect: ReflectCard,
}

export function KoanToolCard(props: KoanToolCardProps) {
  const Renderer = TOOL_RENDERERS[props.toolName] ?? FallbackCard
  return <Renderer args={props.args} result={props.result} inFlight={props.inFlight} />
}

export default KoanToolCard
