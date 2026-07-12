import type { ConversationEntry } from './index'

// ---------------------------------------------------------------------------
// Entry text extraction + transcript serialization
//
// These pure functions are the single source of truth for store-driven find
// (Ctrl-F) and copy-transcript. Both operate on store entries directly rather
// than DOM text, so they cover the full conversation history regardless of
// which rows are currently mounted in the virtualized list.
// ---------------------------------------------------------------------------

// WeakMap cache: entries are reference-stable (M2 structural sharing via Immer
// produce), so each entry's searchable text is computed at most once for the
// lifetime of that reference. This avoids re-JSON.stringify-ing all tool args
// on every find keystroke.
const _searchTextCache = new WeakMap<ConversationEntry, string>()

/**
 * entrySearchText -- extract the searchable plain text from a conversation entry.
 *
 * Returns a string covering the human-visible / searchable content for the
 * given entry variant. Unknown or structure-only types return "". The result
 * is memoized per entry reference via a module-level WeakMap so repeated calls
 * (e.g. on every find-bar keystroke) pay no extra cost after the first call.
 *
 * Pure function; reads no store state and has no side effects beyond the cache.
 */
export function entrySearchText(entry: ConversationEntry): string {
  const cached = _searchTextCache.get(entry)
  if (cached !== undefined) return cached

  const text = _extractText(entry)
  _searchTextCache.set(entry, text)
  return text
}

function _extractText(entry: ConversationEntry): string {
  switch (entry.type) {
    case 'thinking':
      return entry.content

    case 'text':
      return entry.text

    case 'user_message':
      return entry.content

    case 'step':
      return entry.stepName

    case 'debug_step_guidance':
      return entry.content

    case 'phase_boundary':
      // Include both phase name, the message, and the description field
      return [entry.phase, entry.message, entry.description].filter(Boolean).join(' ')

    case 'yield':
      // The prompt and the text of each suggestion label
      return [
        entry.prompt,
        ...entry.suggestions.map(s => s.label),
      ].filter(Boolean).join(' ')

    case 'tool_write':
    case 'tool_edit':
      return entry.file

    case 'tool_bash':
      return entry.command
    case 'tool_read':
      return entry.file
    case 'tool_grep':
      return entry.pattern
    case 'tool_glob':
      return entry.pattern
    case 'tool_web_search':
      return entry.query
    case 'tool_web_fetch':
      return entry.url

    case 'tool_generic':
      return [entry.toolName, entry.summary].filter(Boolean).join(' ')

    case 'tool_koan': {
      // Include tool name plus stringified args and result so the user can
      // search for tool arguments (e.g. a filename passed to koan_artifact_write).
      const parts: string[] = [entry.toolName]
      try { parts.push(JSON.stringify(entry.args)) } catch { /* non-serializable; skip */ }
      if (entry.result != null) {
        try { parts.push(JSON.stringify(entry.result)) } catch { /* non-serializable; skip */ }
      }
      return parts.join(' ')
    }

    case 'tool_failed':
      return [entry.toolName, entry.error].filter(Boolean).join(' ')

    case 'tool_aggregate': {
      // Extract commands from all children so the user can search for
      // filenames, patterns, or paths involved in aggregated exploration.
      const cmds: string[] = []
      for (const c of entry.children) {
        if (c.type === 'tool_read') cmds.push(c.file)
        else if (c.type === 'tool_grep') cmds.push(c.pattern)
        else if (c.type === 'tool_glob') cmds.push(c.pattern)
        else if (c.type === 'tool_bash') cmds.push(c.command)
        else if (c.type === 'tool_web_search') cmds.push(c.query)
        else if (c.type === 'tool_web_fetch') cmds.push(c.url)
      }
      return cmds.join(' ')
    }

    default:
      return ''
  }
}

// ---------------------------------------------------------------------------
// Transcript serialization
// ---------------------------------------------------------------------------

/**
 * entriesToTranscript -- serialize all conversation entries to a plain-text
 * transcript suitable for copying to the clipboard.
 *
 * Each entry is rendered as a type-labeled block separated by blank lines.
 * The output is plain text / light Markdown (no HTML); it does not depend on
 * react-markdown or any DOM API so it can run in any context (e.g. a Web
 * Worker if needed in future).
 *
 * Pure function; reads no store state.
 */
export function entriesToTranscript(entries: ConversationEntry[]): string {
  return entries.map(serializeEntry).filter(Boolean).join('\n\n')
}

function serializeEntry(entry: ConversationEntry): string {
  switch (entry.type) {
    case 'thinking':
      return `[thinking]\n${entry.content}`

    case 'text':
      return entry.text

    case 'user_message':
      return `[user]\n${entry.content}`

    case 'step':
      return `[step ${entry.step}/${entry.totalSteps ?? '?'}] ${entry.stepName}`

    case 'debug_step_guidance':
      return `[step-guidance]\n${entry.content}`

    case 'phase_boundary':
      return `[phase: ${entry.phase}]${entry.description ? ' ' + entry.description : entry.message ? ' ' + entry.message : ''}`

    case 'yield': {
      const lines = [`[yield] ${entry.prompt}`]
      for (const s of entry.suggestions) lines.push(`  - ${s.label}`)
      return lines.join('\n')
    }

    case 'tool_write':
      return `[write] ${entry.file}`

    case 'tool_edit':
      return `[edit] ${entry.file}`

    case 'tool_bash':
      return `[bash] ${entry.command}`
    case 'tool_read':
      return `[read] ${entry.file}`
    case 'tool_grep':
      return `[grep] ${entry.pattern}`
    case 'tool_glob':
      return `[glob] ${entry.pattern}`
    case 'tool_web_search':
      return `[web_search] ${entry.query}`
    case 'tool_web_fetch':
      return `[web_fetch] ${entry.url}`

    case 'tool_generic':
      return `[tool:${entry.toolName}] ${entry.summary}`

    case 'tool_koan': {
      const result = entry.result != null ? '\n' + JSON.stringify(entry.result, null, 2) : ''
      return `[koan:${entry.toolName}]${result}`
    }

    case 'tool_failed':
      return `[failed:${entry.toolName}] ${entry.error}`

    case 'tool_aggregate': {
      const lines = [`[explore ${entry.children.length} ops]`]
      for (const c of entry.children) {
        if (c.type === 'tool_read') lines.push(`  read ${c.file}`)
        else if (c.type === 'tool_grep') lines.push(`  grep ${c.pattern}`)
        else if (c.type === 'tool_glob') lines.push(`  glob ${c.pattern}`)
        else if (c.type === 'tool_bash') lines.push(`  bash ${c.command}`)
        else if (c.type === 'tool_web_search') lines.push(`  web_search ${c.query}`)
        else if (c.type === 'tool_web_fetch') lines.push(`  web_fetch ${c.url}`)
      }
      return lines.join('\n')
    }

    default:
      return ''
  }
}
