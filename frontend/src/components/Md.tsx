/**
 * Md -- renders a markdown string using react-markdown + remark-gfm.
 *
 * Fenced ```mermaid blocks are routed to <MermaidBlock>, which renders them
 * as inline SVG diagrams. All other code blocks (inline and fenced) fall
 * through to react-markdown's default <code> rendering so existing styles in
 * markdown.css are preserved.
 *
 * The `components` object is defined at module scope so its identity is stable
 * across renders. An inline object literal would cause react-markdown to
 * re-register component overrides on every render, which is wasteful on the
 * streaming hot path.
 */

import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { MermaidBlock } from './molecules/MermaidBlock'

// Stable module-scope components map. React-markdown receives this reference
// unchanged on every render, avoiding unnecessary reconciliation work.
const components: Components = {
  code({ className, children, ...rest }) {
    if (className === 'language-mermaid') {
      // Strip the trailing newline that react-markdown appends to fenced block
      // children so mermaid does not see a spurious blank line at the end.
      return <MermaidBlock code={String(children).replace(/\n$/, '')} />
    }
    // Fall through: inline code (no className) and all other fenced blocks
    // render with the default <code> element, preserving markdown.css styles.
    return <code className={className} {...rest}>{children}</code>
  },
}

export function Md({ children }: { children: string }) {
  return (
    <div className="markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {children}
      </ReactMarkdown>
    </div>
  )
}
