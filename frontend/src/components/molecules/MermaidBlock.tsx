/**
 * MermaidBlock -- renders one fenced ```mermaid block as an inline SVG diagram.
 *
 * Rendering is attempted on every change to `code`, making it streaming-
 * friendly: as tokens arrive the component re-renders and re-attempts the
 * mermaid parse. While the diagram is invalid (e.g. partial source mid-stream),
 * the raw source is shown as a plain code block with no error banner to avoid
 * noise. Once the source is valid, the SVG replaces it. If the block is final
 * and still invalid, a full error banner with the parser message appears above
 * the raw source so the user can diagnose the problem.
 *
 * A stale-result guard (renderToken ref) prevents out-of-order async results
 * from overwriting a more-recent render when the prop changes rapidly.
 *
 * Mermaid is initialised once at module load (see below) -- it is a process-
 * wide singleton and must not be re-initialised per component instance.
 *
 * Used in: <Md> (language-mermaid code blocks are routed here).
 */

import { useEffect, useId, useRef, useState, type ReactElement } from 'react'
import mermaid from 'mermaid'
import './MermaidBlock.css'

// Project-wide mermaid configuration. Runs once on first import.
// startOnLoad: false -- we call render() manually; letting mermaid scan the
// DOM automatically would conflict with React's managed subtree.
// securityLevel: 'strict' -- sandboxes SVG output to prevent XSS from
// LLM-generated diagram source.
mermaid.initialize({
  startOnLoad: false,
  securityLevel: 'strict',
})

// mermaid.render() creates temp container nodes (id and "d{id}") in document.body
// for measurement, then removes them. If the calling component unmounts mid-render
// or render rejects after the bomb-icon SVG was injected, those nodes survive and
// stack on the page. Sweep them when we know we are done with this id.
function sweepLeakedMermaidNodes(id: string): void {
  for (const candidate of [id, 'd' + id]) {
    const el = document.getElementById(candidate)
    if (el !== null) el.remove()
  }
}

interface MermaidBlockProps {
  code: string
}

export function MermaidBlock({ code }: MermaidBlockProps): ReactElement {
  const [svg, setSvg]     = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const renderToken       = useRef(0)

  // useId produces strings like ":r0:" which mermaid rejects as CSS selectors.
  // Sanitise to alphanumeric + hyphen and prefix with a static string.
  const rawId      = useId()
  const id         = 'mb-' + rawId.replace(/[^a-zA-Z0-9_-]/g, '-')

  useEffect(() => {
    // Snapshot this invocation's token. The async callback checks it before
    // committing state so a stale response from a superseded render is dropped.
    const token = ++renderToken.current

    // Validate before render() so syntactically invalid input never reaches
    // the renderer. mermaid.render() on bad input both throws AND injects the
    // bomb-icon error SVG into document.body via its temp container; those
    // nodes can leak when the parent unmounts before cleanup runs. parse()
    // with suppressErrors returns false on syntax errors instead of throwing,
    // and never mutates the DOM.
    mermaid
      .parse(code, { suppressErrors: true })
      .then((parsed) => {
        if (token !== renderToken.current) return
        if (parsed === false) {
          setSvg(null)
          setError('mermaid syntax error')
          return
        }
        return mermaid
          .render(id, code)
          .then((result) => {
            if (token !== renderToken.current) return
            setSvg(result.svg)
            setError(null)
          })
          .catch((err: unknown) => {
            if (token !== renderToken.current) return
            setSvg(null)
            setError(err instanceof Error ? err.message : String(err))
            sweepLeakedMermaidNodes(id)
          })
      })
  }, [code, id])

  // On unmount, sweep any mermaid temp nodes for this id that escaped cleanup.
  useEffect(() => {
    return () => { sweepLeakedMermaidNodes(id) }
  }, [id])

  if (error !== null) {
    return (
      <div className="mb-error-container">
        <div className="mb-error-banner">{error}</div>
        <pre className="mb-error-source"><code>{code}</code></pre>
      </div>
    )
  }

  if (svg !== null) {
    return (
      <div className="mb-container">
        {/* dangerouslySetInnerHTML is intentional: mermaid returns a sanitised
            SVG string (securityLevel strict); React cannot render raw SVG
            markup as JSX without a full parse step. */}
        <div className="mb-svg" dangerouslySetInnerHTML={{ __html: svg }} />
      </div>
    )
  }

  // Loading state: first async render is still in flight. Show the raw source
  // as a plain code block to avoid a jarring empty container during streaming.
  return (
    <pre className="mb-error-source"><code>{code}</code></pre>
  )
}

export default MermaidBlock
