/**
 * ToolCommandText — per-family command rendering for exploration tool
 * operations. A formatted text primitive used identically by ToolLogRow
 * (aggregate rows) and ToolCallRow (standalone and single-op fallback
 * rows); owning the family-specific markup in one atom keeps the
 * consumers from drifting.
 *
 * The container carries `title` with the full untruncated text. Read
 * paths left-truncate (directory side) so the basename always survives;
 * patterns, commands, queries, and URL paths right-truncate.
 *
 * Spec: docs/design-system.md — Atoms → ToolCommandText.
 */

import './ToolCommandText.css'

export type ExplorationFamily =
  | 'read'
  | 'grep'
  | 'glob'
  | 'bash'
  | 'web_search'
  | 'web_fetch'

export interface ToolCommandTextProps {
  family: ExplorationFamily
  path?: string // read
  range?: string // read, preformatted "1–80"
  pattern?: string // grep, glob
  scope?: string // grep, glob — preformatted, e.g. "in koan/ · *.py"
  command?: string // bash
  query?: string // web_search
  url?: string // web_fetch
  running?: boolean
  error?: boolean
}

function splitPath(p: string): { dir: string; base: string } {
  const i = p.lastIndexOf('/')
  return i === -1
    ? { dir: '', base: p }
    : { dir: p.slice(0, i + 1), base: p.slice(i + 1) }
}

function splitUrl(u: string): { host: string; path: string } {
  const stripped = u.replace(/^[a-z][a-z0-9+.-]*:\/\//i, '')
  const i = stripped.indexOf('/')
  return i === -1
    ? { host: stripped, path: '' }
    : { host: stripped.slice(0, i), path: stripped.slice(i) }
}

function firstLine(command: string): string {
  const i = command.indexOf('\n')
  return i === -1 ? command : command.slice(0, i)
}

function fullText(p: ToolCommandTextProps): string {
  switch (p.family) {
    case 'read':
      return `${p.path ?? ''}${p.range ? `:${p.range}` : ''}`
    case 'grep':
    case 'glob':
      return `${p.pattern ?? ''}${p.scope ? ` ${p.scope}` : ''}`
    case 'bash':
      return p.command ?? ''
    case 'web_search':
      return p.query ?? ''
    case 'web_fetch':
      return p.url ?? ''
  }
}

function body(p: ToolCommandTextProps) {
  switch (p.family) {
    case 'read': {
      const { dir, base } = splitPath(p.path ?? '')
      return (
        <>
          {dir && (
            <span className="tct-dir">
              <bdi>{dir}</bdi>
            </span>
          )}
          <span className="tct-primary tct-base">{base}</span>
          {p.range && <span className="tct-range">:{p.range}</span>}
        </>
      )
    }
    case 'grep':
    case 'glob':
      return (
        <>
          <span className="tct-primary tct-truncate">{p.pattern}</span>
          {p.scope && <span className="tct-scope">{p.scope}</span>}
        </>
      )
    case 'bash':
      return (
        <>
          <span className="tct-sigil">$</span>
          <span className="tct-primary tct-truncate">
            {firstLine(p.command ?? '')}
          </span>
        </>
      )
    case 'web_search':
      return <span className="tct-primary tct-truncate">{p.query}</span>
    case 'web_fetch': {
      const { host, path } = splitUrl(p.url ?? '')
      return (
        <>
          <span className="tct-primary tct-host">{host}</span>
          {path && <span className="tct-urlpath tct-truncate">{path}</span>}
        </>
      )
    }
  }
}

export function ToolCommandText(props: ToolCommandTextProps) {
  const state = props.running ? ' tct--running' : props.error ? ' tct--error' : ''
  return (
    <span className={`tct${state}`} title={fullText(props)}>
      {body(props)}
    </span>
  )
}

export default ToolCommandText
