/*
 * EVENT TYPE -> MOLECULE MAPPING (final, no gaps)
 * -------------------------------------------------
 * thinking             -> ThinkingBlock + Md
 * text                 -> ProseCard + Md
 * tool_write/edit      -> ToolCallRow
 * tool_bash            -> ToolCallRow
 * tool_generic         -> ToolCallRow (rare; non-koan custom tools only)
 * tool_koan            -> KoanToolCard (dispatches by toolName;
 *                          koan_complete_step and koan_set_phase
 *                          suppressed inside the card)
 * step                 -> StepHeader
 * debug_step_guidance  -> StepGuidancePill + Md
 * user_message         -> UserBubble + Md
 * phase_boundary       -> PhaseMarker
 * yield                -> YieldPanel
 * pendingThinking      -> ThinkingBlock (always expanded, plain pre-wrap text)
 * pendingText          -> ProseCard + Md + streaming cursor
 */

// Moved from App.tsx in M2: ContentStream, renderEntry, renderAggregate,
// aggregate helpers, ConnectedSteeringBar, plus the four new sub-components
// (CommittedList, StreamingLeaf, FeedbackFooter, ContentStream).
// M4: virtualized with react-virtuoso; CommittedList replaced by Virtuoso;
// useAutoScroll removed in favor of followOutput; FindBar added.

import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Virtuoso, type VirtuosoHandle } from 'react-virtuoso'

import { useStore, ConversationEntry } from '../../store/index'
import type { AggregateChild, AggregateReadChild, AggregateGrepChild,
              AggregateLsChild, ToolAggregateEntry } from '../../store/index'
import {
  selectFocusedEntries,
  selectPendingThinking,
  selectPendingText,
  selectIsThinking,
  selectShowFeedback,
  selectSteering,
  selectFeedbackCommands,
  selectCompletionPresent,
} from '../../store/selectors'
import { entrySearchText, entriesToTranscript } from '../../store/transcript'
import * as api from '../../api/client'
// useAutoScroll removed in M4: react-virtuoso followOutput="auto" + a size-observed
// Footer replace the ResizeObserver stick-to-bottom. The two mechanisms conflict;
// stacking them causes scroll jitter on a virtualizer.

import { ThinkingBlock } from '../molecules/ThinkingBlock'
import { ProseCard } from '../molecules/ProseCard'
import { ToolCallRow } from '../molecules/ToolCallRow'
import { ToolLogRow } from '../molecules/ToolLogRow'
import { ToolStatBlock } from '../molecules/ToolStatBlock'
import { ToolAggregateCard } from '../molecules/ToolAggregateCard'
import { StepGuidancePill } from '../molecules/StepGuidancePill'
import { FeedbackInput } from '../molecules/FeedbackInput'
import { UserBubble } from '../molecules/UserBubble'
import { PhaseMarker } from '../molecules/PhaseMarker'
import { YieldPanel } from '../molecules/YieldPanel'
import { StepHeader } from '../molecules/StepHeader'
import { SteeringBar } from '../molecules/SteeringBar'
import { KoanToolCard } from '../molecules/KoanToolCard'
import { FindBar } from '../molecules/FindBar'

import { Md } from '../Md'
import { formatElapsed } from '../../hooks/useElapsed'

import './ContentStream.css'

// ---------------------------------------------------------------------------
// Aggregate rendering helpers -- pure functions, next to renderEntry so the
// data flow stays readable. Each maps AggregateChild state to display strings
// or further structured pieces consumed by the card / row components.
// ---------------------------------------------------------------------------

function pluralizeOps(n: number): string {
  return n === 1 ? '1 op' : `${n} ops`
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  const kb = n / 1024
  if (kb < 1024) return `${kb.toFixed(1)} KB`
  return `${(kb / 1024).toFixed(1)} MB`
}

function childCommand(child: AggregateChild): string {
  switch (child.tool) {
    case 'read': return child.lines ? `${child.file}:${child.lines}` : child.file
    case 'grep': return child.pattern
    case 'ls':   return child.path
  }
}

function childMetric(child: AggregateChild): string | undefined {
  switch (child.tool) {
    case 'read': {
      if (child.linesRead != null && child.bytesRead != null) {
        return `${child.linesRead} lines · ${formatBytes(child.bytesRead)}`
      }
      if (child.linesRead != null) return `${child.linesRead} lines`
      return undefined
    }
    case 'grep': {
      if (child.matches != null && child.filesMatched != null) {
        return `${child.matches} matches · ${child.filesMatched} files`
      }
      if (child.matches != null) return `${child.matches} matches`
      return undefined
    }
    case 'ls': {
      if (child.entries != null) return `${child.entries} entries`
      return undefined
    }
  }
}

function shortBasename(path: string): string {
  const slash = path.lastIndexOf('/')
  return slash >= 0 ? path.slice(slash + 1) : path
}

function runningLabelFor(child: AggregateChild): string {
  switch (child.tool) {
    case 'read': return `reading ${shortBasename(child.file)}`
    case 'grep': return 'grepping'
    case 'ls':   return `listing ${shortBasename(child.path)}`
  }
}

function findRunningChild(children: AggregateChild[]): AggregateChild | undefined {
  return children.find(c => c.inFlight)
}

function groupChildrenByTool(children: AggregateChild[]): {
  read: AggregateReadChild[]; grep: AggregateGrepChild[]; ls: AggregateLsChild[]
} {
  const read: AggregateReadChild[] = []
  const grep: AggregateGrepChild[] = []
  const ls: AggregateLsChild[] = []
  for (const c of children) {
    if (c.tool === 'read') read.push(c)
    else if (c.tool === 'grep') grep.push(c)
    else ls.push(c)
  }
  return { read, grep, ls }
}

function readMetaLines(children: AggregateReadChild[]): string[] {
  let totalLines = 0
  let totalBytes = 0
  let anyLineMetric = false
  const files = new Set<string>()
  for (const c of children) {
    if (c.linesRead != null) { totalLines += c.linesRead; anyLineMetric = true }
    if (c.bytesRead != null) { totalBytes += c.bytesRead }
    files.add(c.file)
  }
  const lines: string[] = []
  if (anyLineMetric) {
    lines.push(totalBytes > 0
      ? `${totalLines} lines · ${formatBytes(totalBytes)}`
      : `${totalLines} lines`)
  }
  if (files.size !== children.length) {
    // More than one read hit the same file -- worth mentioning file count.
    lines.push(`${files.size} ${files.size === 1 ? 'file' : 'files'} touched`)
  }
  return lines
}

function grepMetaLines(children: AggregateGrepChild[]): string[] {
  let totalMatches = 0
  let totalFiles = 0
  let anyMetric = false
  for (const c of children) {
    if (c.matches != null) { totalMatches += c.matches; anyMetric = true }
    if (c.filesMatched != null) { totalFiles += c.filesMatched }
  }
  const lines: string[] = []
  if (anyMetric) lines.push(`${totalMatches} matches`)
  if (totalFiles > 0) lines.push(`${totalFiles} ${totalFiles === 1 ? 'file' : 'files'} searched`)
  return lines
}

function lsMetaLines(children: AggregateLsChild[]): string[] {
  let totalEntries = 0
  let totalDirs = 0
  let anyMetric = false
  for (const c of children) {
    if (c.entries != null) { totalEntries += c.entries; anyMetric = true }
    if (c.directories != null) totalDirs += c.directories
  }
  const lines: string[] = []
  if (anyMetric) lines.push(`${totalEntries} entries`)
  if (totalDirs > 0) lines.push(`${totalDirs} ${totalDirs === 1 ? 'directory' : 'directories'}`)
  return lines
}

function aggregateElapsedMs(agg: ToolAggregateEntry, nowMs: number): number {
  const running = findRunningChild(agg.children)
  if (running) {
    return Math.max(0, nowMs - agg.startedAtMs)
  }
  let latest = agg.startedAtMs
  for (const c of agg.children) {
    if (c.completedAtMs != null && c.completedAtMs > latest) latest = c.completedAtMs
  }
  return Math.max(0, latest - agg.startedAtMs)
}

function renderAggregate(entry: ToolAggregateEntry) {
  const children = entry.children
  if (children.length === 0) return null

  // Single-child aggregates render as a standalone ToolCallRow, matching the
  // pre-aggregation visual for the common case where no grouping has happened
  // yet. The row upgrades to a card on the next consecutive exploration tool.
  if (children.length === 1) {
    const c = children[0]
    return (
      <ToolCallRow
        tool={c.tool}
        command={childCommand(c)}
        status={c.inFlight ? 'running' : 'done'}
        metric={childMetric(c)}
      />
    )
  }

  // Two or more children: render the full two-pane aggregate card.
  const groups = groupChildrenByTool(children)
  const running = findRunningChild(children)
  const runningLabel = running ? runningLabelFor(running) : undefined
  const elapsedMs = aggregateElapsedMs(entry, Date.now())

  const stats = [
    groups.read.length > 0 && (
      <ToolStatBlock
        key="read"
        type="read"
        name="read"
        opCount={pluralizeOps(groups.read.length)}
        metaLines={readMetaLines(groups.read)}
        active={running?.tool === 'read'}
      />
    ),
    groups.grep.length > 0 && (
      <ToolStatBlock
        key="grep"
        type="grep"
        name="grep"
        opCount={pluralizeOps(groups.grep.length)}
        metaLines={grepMetaLines(groups.grep)}
        active={running?.tool === 'grep'}
      />
    ),
    groups.ls.length > 0 && (
      <ToolStatBlock
        key="ls"
        type="ls"
        name="ls"
        opCount={pluralizeOps(groups.ls.length)}
        metaLines={lsMetaLines(groups.ls)}
        active={running?.tool === 'ls'}
      />
    ),
  ].filter(Boolean)

  const logRows = children.map((c, j) => (
    <ToolLogRow
      key={j}
      status={c.inFlight ? 'running' : c.tool}
      command={childCommand(c)}
      metric={c.inFlight
        ? (c.tool === 'read' ? 'reading...' : c.tool === 'grep' ? 'grepping...' : 'listing...')
        : childMetric(c)}
    />
  ))

  return (
    <ToolAggregateCard
      operationCount={children.length}
      runningLabel={runningLabel}
      elapsed={elapsedMs > 0 ? formatElapsed(elapsedMs) : undefined}
      statsPane={stats}
      logPane={logRows}
    />
  )
}

/**
 * renderEntryBody -- pure entry -> elements dispatch.
 *
 * Converts a single ConversationEntry to its display elements. No index
 * parameter: keys for array reconciliation live on EntryRow, not here.
 * The yield case uses the imperative useStore.getState() (not a hook) to
 * read transient state at render time without subscribing to it.
 */
function renderEntryBody(entry: ConversationEntry) {
  switch (entry.type) {
    case 'thinking':
      return <ThinkingBlock><Md>{entry.content}</Md></ThinkingBlock>
    case 'text':
      return <ProseCard><Md>{entry.text}</Md></ProseCard>
    case 'tool_aggregate':
      return renderAggregate(entry)
    case 'tool_write':
      return <ToolCallRow tool="write" command={entry.file} status={entry.inFlight ? 'running' : 'done'} attachments={entry.attachments} />
    case 'tool_edit':
      return <ToolCallRow tool="edit" command={entry.file} status={entry.inFlight ? 'running' : 'done'} attachments={entry.attachments} />
    case 'tool_bash':
      return <ToolCallRow tool="bash" command={entry.command} status={entry.inFlight ? 'running' : 'done'} attachments={entry.attachments} />
    // tool_generic is reached only by non-koan custom tools post-M1;
    // koan MCP tools now create ToolKoanEntry via the broadened KOAN_MCP_TOOLS set.
    case 'tool_generic':
      return <ToolCallRow tool={entry.toolName} command={entry.summary} status={entry.inFlight ? 'running' : 'done'} attachments={entry.attachments} />
    case 'tool_koan':
      // toolInput is the M1 aggregate field for live partial-args rendering.
      // Passed alongside args so ReflectCard (which reads args) continues
      // to work unchanged until M3 refactors ToolKoanEntry split-source.
      return (
        <KoanToolCard
          toolName={entry.toolName}
          args={entry.args}
          toolInput={entry.toolInput ?? null}
          result={entry.result}
          inFlight={entry.inFlight}
        />
      )
    case 'step':
      return <StepHeader stepNumber={entry.step} totalSteps={entry.totalSteps ?? 0} stepName={entry.stepName} />
    case 'debug_step_guidance':
      return <StepGuidancePill status="active" defaultExpanded={false}><Md>{entry.content}</Md></StepGuidancePill>
    case 'user_message': {
      const ts = new Date(entry.timestampMs).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      return <UserBubble timestamp={ts}><Md>{entry.content}</Md></UserBubble>
    }
    case 'phase_boundary':
      return <PhaseMarker name={entry.phase} description={entry.description || entry.message} />
    case 'yield': {
      const state = useStore.getState()
      const setChatDraft = state.setChatDraft
      // Compute changed artifacts at render time using the imperative store API.
      // By the time lastTouchpointMs updates (on chat send), this yield entry is
      // replaced by a user_message entry so stale changedArtifacts are never seen.
      const ltp = state.lastTouchpointMs
      const changedArtifacts = Object.values(state.run?.artifacts ?? {})
        .filter(a => a.modifiedAt > (ltp ?? 0))
        .map(a => a.path)
      return (
        <YieldPanel
          prompt={entry.prompt || 'What would you like to do next?'}
          suggestions={entry.suggestions}
          changedArtifacts={changedArtifacts}
          onSelect={s => setChatDraft(s.command ? `/${s.id} ${s.command}` : `/${s.id} `)}
        />
      )
    }
    default:
      return null
  }
}

/**
 * EntryRow -- per-entry memo boundary in the committed list.
 *
 * Re-renders only when its `entry` reference changes. M2's structural
 * sharing (Immer produce) keeps unchanged entries' references equal across
 * patches, so only the mutated entry re-renders on each patch application.
 * This makes committed-list re-render O(changed) instead of O(history).
 *
 * Keyed by entryId (M1 stable server-assigned key) in Virtuoso computeItemKey,
 * with index fallback for defensive correctness.
 */
const EntryRow = React.memo(function EntryRow({ entry }: { entry: ConversationEntry }) {
  return renderEntryBody(entry)
})

// ---------------------------------------------------------------------------
// ConnectedSteeringBar -- moved from App.tsx; updated to use selectSteering
// for referential stability (EMPTY_STEERING constant when no messages).
// ---------------------------------------------------------------------------

function ConnectedSteeringBar() {
  const steering = useStore(selectSteering)
  return <SteeringBar messages={steering.map(m => m.content)} />
}

// ---------------------------------------------------------------------------
// StreamingLeaf
//
// The ONLY component that re-renders on every token patch. It subscribes to
// the pending fields (pendingThinking, pendingText, isThinking) and the
// hasEntries boolean. Everything else (FeedbackFooter) is isolated from token
// patches by their narrow subscriptions.
//
// Tailored streaming rendering (M2 decision 6):
//   - pending thinking -> plain pre-wrapped text (cs-pending-thinking div),
//     NOT <Md>; avoids O(n^2) markdown re-parse during long thinking blocks.
//   - pending answer text -> live <Md> (coalesced to one parse per rAF frame).
//   Both snap to committed <Md> once the entry is flushed into the Virtuoso list.
// ---------------------------------------------------------------------------

/**
 * StreamingLeaf -- renders the in-flight / pending conversation tail.
 *
 * Subscription scope: selectIsThinking, selectPendingThinking, selectPendingText,
 * and a hasEntries boolean. This is the sole component that re-renders on every
 * token patch. React.memo isolates it from ContentStream re-renders (e.g.
 * paletteOpen toggle) that do not change any pending field.
 */
const StreamingLeaf = React.memo(function StreamingLeaf() {
  const isThinking = useStore(selectIsThinking)
  const pendingThinking = useStore(selectPendingThinking)
  const pendingText = useStore(selectPendingText)
  // Boolean subscription: re-renders only when the first entry is added
  // (false -> true), not on every subsequent patch.
  const hasEntries = useStore(s => selectFocusedEntries(s).length > 0)
  const isWaiting = !hasEntries && !isThinking && !pendingText
  return (
    <>
      {isWaiting && (
        <div className="waiting-indicator">
          <span className="pulse-dot">●</span>
          <span>Starting agent…</span>
        </div>
      )}
      {isThinking && pendingThinking && (
        <ThinkingBlock defaultExpanded={true}>
          {/* Plain pre-wrapped text while streaming; snaps to <Md> on commit. */}
          <div className="cs-pending-thinking">{pendingThinking}</div>
        </ThinkingBlock>
      )}
      {isThinking && !pendingThinking && (
        <div className="thinking-indicator">
          <span className="pulse-dot">●</span>
          <span>Thinking…</span>
        </div>
      )}
      {pendingText && (
        <ProseCard><Md>{pendingText}</Md><span className="stream-cursor" /></ProseCard>
      )}
    </>
  )
})

// ---------------------------------------------------------------------------
// FeedbackFooter
//
// The persistent footer rendered below the conversation entries. Subscribes
// to selectSteering (via ConnectedSteeringBar), selectFeedbackCommands, and
// selectCompletionPresent -- never to pending fields or s.run by reference.
// Receives paletteOpen and onPaletteToggle from ContentStream (local UI state).
// ---------------------------------------------------------------------------

interface FeedbackFooterProps {
  paletteOpen: boolean
  onPaletteToggle: (open: boolean) => void
}

/**
 * FeedbackFooter -- the steering bar + feedback input below the conversation.
 *
 * Subscription scope: selectSteering (via ConnectedSteeringBar),
 * selectFeedbackCommands, selectCompletionPresent. Never reads pending fields;
 * token patches do not re-render this component.
 */
function FeedbackFooter({ onPaletteToggle }: FeedbackFooterProps) {
  const commands = useStore(selectFeedbackCommands)
  const completionPresent = useStore(selectCompletionPresent)
  return (
    <>
      <ConnectedSteeringBar />
      {/* ArtifactReviewPin removed in M6 -- koan_artifact_propose deleted in M5. */}
      <FeedbackInput
        onSend={(msg, attachments) => {
          // Mark yield resolution so sidebar and yield panel reflect the new
          // "changed since last touchpoint" baseline going forward.
          useStore.getState().setLastTouchpointMs(Date.now())
          return api.sendChatMessage(msg, attachments)
        }}
        disabled={completionPresent}
        availableCommands={commands}
        onPaletteToggle={onPaletteToggle}
      />
    </>
  )
}

// ---------------------------------------------------------------------------
// FooterContext -- context threaded from ContentStream into the Virtuoso Footer.
//
// Virtuoso renders Footer as a component inside its scroll content, after all
// items. Using Virtuoso's context prop is the only way to pass runtime state
// into Footer without making Footer a closure that recreates on every render
// (which would cause Virtuoso to unmount/remount it).
// ---------------------------------------------------------------------------

interface FooterContext {
  paletteOpen: boolean
  onPaletteToggle: (open: boolean) => void
  showFeedback: boolean
}

// ---------------------------------------------------------------------------
// Footer -- stable Virtuoso footer component (module-level, not a closure).
//
// Must be defined at module scope (not inside ContentStream) so its reference
// is stable across renders. Virtuoso checks `components.Footer` by reference;
// a recreated function type causes it to unmount and remount the footer on
// every ContentStream re-render, which resets FeedbackInput state.
//
// Renders StreamingLeaf (always) and FeedbackFooter (when showFeedback).
// Both sub-components dim when paletteOpen via the .content-stream--faded
// selector on a wrapper class (see ContentStream.css).
// ---------------------------------------------------------------------------

/**
 * Footer -- stable Virtuoso footer rendered after all conversation items.
 *
 * Receives ContentStream's runtime state through Virtuoso's context prop.
 * StreamingLeaf and FeedbackFooter are wrapped in named classes so the
 * palette-dim CSS can target them independently (.cs-streaming-leaf-wrap dims;
 * .cs-feedback-footer-wrap stays crisp -- see ContentStream.css).
 */
function Footer({ context }: { context: FooterContext }) {
  return (
    <>
      <div className="cs-streaming-leaf-wrap">
        <StreamingLeaf />
      </div>
      {context.showFeedback && (
        <div className="cs-feedback-footer-wrap">
          <FeedbackFooter
            paletteOpen={context.paletteOpen}
            onPaletteToggle={context.onPaletteToggle}
          />
        </div>
      )}
    </>
  )
}

// ---------------------------------------------------------------------------
// ContentStream (exported)
//
// The top-level conversation container. Subscribes to selectFocusedEntries
// (for Virtuoso data and find-bar matches) and selectShowFeedback (for the
// footer context). Does NOT subscribe to any pending field -- only
// StreamingLeaf does. Token patches re-render only StreamingLeaf.
//
// Virtualization: react-virtuoso with customScrollParent=.content-column.
// The existing .content-column (overflow-y:auto, padding, container-type)
// is preserved as the scroll container so layout is unchanged.
//
// Find: Cmd/Ctrl+F (while mounted) opens FindBar; prev/next scroll to
// matching entries via virtuosoRef.scrollToIndex. Copy-transcript serializes
// all store entries via entriesToTranscript.
// ---------------------------------------------------------------------------

/**
 * ContentStream -- outer container for the conversation area.
 *
 * Subscription scope: selectFocusedEntries, selectShowFeedback. Does NOT
 * subscribe to any pending field (selectPendingText, selectPendingThinking,
 * selectIsThinking) -- only StreamingLeaf does. Token patches re-render only
 * StreamingLeaf; ContentStream is not invalidated on each streaming token.
 *
 * Uses ref-state pattern for the scroll parent: captures the .content-column
 * DOM node into state via a ref callback; mounts Virtuoso only when non-null
 * so Virtuoso is never constructed before its customScrollParent exists.
 */
export function ContentStream() {
  const showFeedback = useStore(selectShowFeedback)
  const entries = useStore(selectFocusedEntries)

  const [paletteOpen, setPaletteOpen] = useState(false)

  // Ref-state pattern for Virtuoso customScrollParent: the ref callback writes
  // the DOM node into state; Virtuoso mounts on the second render once non-null.
  const [scrollParent, setScrollParent] = useState<HTMLElement | null>(null)

  const virtuosoRef = useRef<VirtuosoHandle>(null)

  // atBottom tracks Virtuoso's bottom state for the fallback scroll comment
  // (followOutput="auto" is the primary mechanism; see ContentStream.css).
  const atBottomRef = useRef(true)
  const [, setAtBottom] = useState(true)
  function onAtBottomChange(bottom: boolean) {
    atBottomRef.current = bottom
    setAtBottom(bottom)
  }

  // ---- Find state ---------------------------------------------------------
  const [findOpen, setFindOpen] = useState(false)
  const [findQuery, setFindQuery] = useState('')
  const [currentMatchIdx, setCurrentMatchIdx] = useState(0)

  // matches: entry indices where the entry's searchable text contains findQuery.
  // entrySearchText is WeakMap-memoized so this useMemo only re-runs when
  // entries or findQuery changes, not on every token patch.
  const matches = useMemo(() => {
    if (!findQuery) return []
    const q = findQuery.toLowerCase()
    const result: number[] = []
    for (let i = 0; i < entries.length; i++) {
      if (entrySearchText(entries[i]).toLowerCase().includes(q)) result.push(i)
    }
    return result
  }, [entries, findQuery])

  // Intercept Cmd/Ctrl+F while ContentStream is mounted; scoped to this
  // component so native find works on all other views (settings, memory, etc.).
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'f') {
        e.preventDefault()
        setFindOpen(true)
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [])

  // ---- Find handlers ------------------------------------------------------

  function closeFindBar() {
    setFindOpen(false)
    setFindQuery('')
    setCurrentMatchIdx(0)
  }

  /**
   * goPrev -- navigate to the previous find match and scroll to it.
   * Wraps around from first to last.
   */
  function goPrev() {
    if (matches.length === 0) return
    const idx = (currentMatchIdx - 1 + matches.length) % matches.length
    setCurrentMatchIdx(idx)
    virtuosoRef.current?.scrollToIndex({ index: matches[idx], align: 'center' })
  }

  /**
   * goNext -- navigate to the next find match and scroll to it.
   * Wraps around from last to first.
   */
  function goNext() {
    if (matches.length === 0) return
    const idx = (currentMatchIdx + 1) % matches.length
    setCurrentMatchIdx(idx)
    virtuosoRef.current?.scrollToIndex({ index: matches[idx], align: 'center' })
  }

  /**
   * copyTranscript -- serialize all entries to plain text and write to clipboard.
   * Operates on the full store entries array so it covers the entire history
   * regardless of which rows are currently mounted in the virtualized list.
   */
  function copyTranscript() {
    navigator.clipboard.writeText(entriesToTranscript(entries))
  }

  // ---- Virtuoso context ---------------------------------------------------

  const footerContext: FooterContext = {
    paletteOpen,
    onPaletteToggle: setPaletteOpen,
    showFeedback,
  }

  // -------------------------------------------------------------------------

  return (
    <div className="content-column" ref={setScrollParent}>
      {/* FindBar sticky anchor: position:sticky keeps the find bar visible as the
          user scrolls. pointer-events:none on the wrapper avoids capturing clicks
          in the left portion; the FindBar element itself re-enables them. */}
      {findOpen && (
        <div className="cs-findbar-sticky">
          <FindBar
            query={findQuery}
            onQueryChange={q => { setFindQuery(q); setCurrentMatchIdx(0) }}
            matchCount={matches.length}
            currentMatch={matches.length > 0 ? currentMatchIdx + 1 : 0}
            onPrev={goPrev}
            onNext={goNext}
            onClose={closeFindBar}
            onCopyTranscript={copyTranscript}
          />
        </div>
      )}
      {scrollParent && (
        // Wrapper for the palette-dim class. Applying content-stream--faded here
        // (rather than on the Virtuoso element) avoids interfering with Virtuoso's
        // internal flex layout. CSS descendant selectors target .cs-item and
        // .cs-streaming-leaf-wrap to dim them; .cs-feedback-footer-wrap is omitted
        // so the feedback input stays crisp. See ContentStream.css.
        <div className={paletteOpen ? 'content-stream content-stream--faded' : 'content-stream'}>
          <Virtuoso<ConversationEntry, FooterContext>
            ref={virtuosoRef}
            customScrollParent={scrollParent}
            data={entries}
            computeItemKey={(i, e) => e.entryId ?? String(i)}
            itemContent={(_i, e) => (
              // padding-bottom reproduces the flex gap from .content-stream.
              // Must be padding not margin: margin collapse breaks Virtuoso's
              // per-item height measurement and causes scroll jitter.
              // Value: var(--gap-content) = 20px (variables.css line 153).
              <div className="cs-item">
                <EntryRow entry={e} />
              </div>
            )}
            followOutput="auto"
            atBottomStateChange={onAtBottomChange}
            context={footerContext}
            components={{ Footer }}
          />
        </div>
      )}
    </div>
  )
}
