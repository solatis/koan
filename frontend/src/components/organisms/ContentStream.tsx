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
import type { ToolAggregateEntry } from '../../store/index'
import {
  selectFocusedEntries,
  selectPendingThinking,
  selectPendingText,
  selectIsThinking,
  selectShowFeedback,
  selectSteering,
  selectFeedbackCommands,
  selectCompletionPresent,
  selectPhase,
  selectArtifacts,
  formatPhaseName,
} from '../../store/selectors'
import { entrySearchText, entriesToTranscript } from '../../store/transcript'
import * as api from '../../api/client'
// useAutoScroll removed in M4: react-virtuoso followOutput="auto" + a size-observed
// Footer replace the ResizeObserver stick-to-bottom. The two mechanisms conflict;
// stacking them causes scroll jitter on a virtualizer.

import { ThinkingBlock } from '../molecules/ThinkingBlock'
import { ProseCard } from '../molecules/ProseCard'
import { ToolCallRow } from '../molecules/ToolCallRow'
import { ToolAggregateCard } from './ToolAggregateCard'
import { groupExplorationOps } from './toolAggregateGrouping'
import { StepGuidancePill } from '../molecules/StepGuidancePill'
import { FeedbackInput } from '../molecules/FeedbackInput'
import { UserBubble } from '../molecules/UserBubble'
import { YieldPanel } from '../molecules/YieldPanel'
import { StepHeader } from '../molecules/StepHeader'
import { PhaseTitleBar } from '../molecules/PhaseTitleBar'
import { ContextCard } from '../molecules/ContextCard'
import { ReturnBanner } from '../molecules/ReturnBanner'
import { SteeringBar } from '../molecules/SteeringBar'
import { KoanToolCard } from '../molecules/KoanToolCard'
import { FindBar } from '../molecules/FindBar'

import { Md } from '../Md'
import { useElapsed } from '../../hooks/useElapsed'
import { toExplorationOp, runningLabelFor, findRunningChild } from './explorationAdapter'

import './ContentStream.css'

/**
 * RenderAggregateCard — the live aggregate card for a run of 2+ consecutive
 * exploration operations.
 *
 * A React component (not a plain function) so it can call `useElapsed` for a
 * live-ticking elapsed string. The old plain-function `renderAggregate`
 * computed a frozen `Date.now()` snapshot; `useElapsed` re-renders every
 * second while the card is mounted, which is the correct behaviour for an
 * in-flight card (it ticks from "0m 00s"). Elapsed is always passed —
 * suppression at 0ms is intentionally dropped so the header shows the timer
 * from the start.
 */
function RenderAggregateCard({ entry }: { entry: ToolAggregateEntry }) {
  const children = entry.children
  if (children.length === 0) return null

  // Map children to ExplorationOp[] and group by family.
  const ops = children.map((c, i) => toExplorationOp(c, i))
  const groups = groupExplorationOps(ops)
  const running = findRunningChild(children)
  const runningLabel = running ? runningLabelFor(running) : undefined
  const elapsed = useElapsed(entry.startedAtMs)

  return (
    <ToolAggregateCard
      groups={groups}
      operationCount={children.length}
      runningLabel={runningLabel}
      elapsed={elapsed}
    />
  )
}

/**
 * renderEntryBody -- pure entry -> elements dispatch.
 *
 * Converts a single ConversationEntry to its display elements. No index
 * parameter: keys for array reconciliation live on EntryRow, not here.
 * The historical flag, when true, suppresses interactive entries (yield)
 * and passes teal-accent styling through to ProseCard and StepHeader.
 * The yield case uses the imperative useStore.getState() (not a hook) to
 * read transient state at render time without subscribing to it.
 */
function renderEntryBody(entry: ConversationEntry, historical: boolean) {
  switch (entry.type) {
    case 'thinking':
      return <ThinkingBlock><Md>{entry.content}</Md></ThinkingBlock>
    case 'text':
      return <ProseCard historical={historical}><Md>{entry.text}</Md></ProseCard>
    case 'tool_aggregate':
      return <RenderAggregateCard entry={entry} />
    case 'tool_write':
      return <ToolCallRow tool="write" command={entry.file} status={entry.inFlight ? 'running' : 'done'} attachments={entry.attachments} />
    case 'tool_edit':
      return <ToolCallRow tool="edit" command={entry.file} status={entry.inFlight ? 'running' : 'done'} attachments={entry.attachments} />
    case 'tool_bash': {
      // Bash as a top-level entry uses the family variant when it has
      // aggregate-child fields (startedAtMs populated by the exploration path);
      // the non-exploration legacy path renders the plain ToolCallRow.
      const isExploration = entry.startedAtMs !== undefined && entry.startedAtMs > 0
      if (isExploration) {
        const op = toExplorationOp(entry, 0)
        return (
          <ToolCallRow
            tool="bash"
            command={entry.command}
            status={op.status}
            family="bash"
            commandData={op.command}
            metric={op.metric}
            metricTone={op.metricTone}
            attachments={entry.attachments}
          />
        )
      }
      return <ToolCallRow tool="bash" command={entry.command} status={entry.inFlight ? 'running' : 'done'} attachments={entry.attachments} />
    }
    case 'tool_read': {
      const op = toExplorationOp(entry, 0)
      return (
        <ToolCallRow
          tool="read"
          command={entry.file}
          status={op.status}
          family="read"
          commandData={op.command}
          metric={op.metric}
          metricTone={op.metricTone}
          attachments={entry.attachments}
        />
      )
    }
    case 'tool_grep': {
      const op = toExplorationOp(entry, 0)
      return (
        <ToolCallRow
          tool="grep"
          command={entry.pattern}
          status={op.status}
          family="grep"
          commandData={op.command}
          metric={op.metric}
          metricTone={op.metricTone}
          attachments={entry.attachments}
        />
      )
    }
    case 'tool_glob': {
      const op = toExplorationOp(entry, 0)
      return (
        <ToolCallRow
          tool="glob"
          command={entry.pattern}
          status={op.status}
          family="glob"
          commandData={op.command}
          metric={op.metric}
          attachments={entry.attachments}
        />
      )
    }
    case 'tool_web_search': {
      const op = toExplorationOp(entry, 0)
      return (
        <ToolCallRow
          tool="web_search"
          command={entry.query}
          status={op.status}
          family="web_search"
          commandData={op.command}
          metric={op.metric}
          attachments={entry.attachments}
        />
      )
    }
    case 'tool_web_fetch': {
      const op = toExplorationOp(entry, 0)
      return (
        <ToolCallRow
          tool="web_fetch"
          command={entry.url}
          status={op.status}
          family="web_fetch"
          commandData={op.command}
          metric={op.metric}
          attachments={entry.attachments}
        />
      )
    }
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
      return <StepHeader historical={historical} stepNumber={entry.step} totalSteps={entry.totalSteps ?? 0} stepName={entry.stepName} />
    case 'debug_step_guidance':
      return <StepGuidancePill status="active" defaultExpanded={false}><Md>{entry.content}</Md></StepGuidancePill>
    case 'user_message': {
      const ts = new Date(entry.timestampMs).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      return <UserBubble timestamp={ts}><Md>{entry.content}</Md></UserBubble>
    }
    case 'phase_boundary':
      // Suppressed: redundant when only one phase's entries are visible.
      // The PhaseTitleBar already identifies the current phase.
      // If "all phases" mode is ever reintroduced, remove the early return.
      return null
    case 'yield': {
      if (historical) return null
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
          // Phase metadata -> mechanical POST to /api/phase (no chat draft, no
          // model turn in the old phase). Free-text -> draft the raw command
          // (no /${s.id} prefix -- the slash form would be misrewritten by
          // transformCommand as a phase transition).
          onSelect={s => {
            if (s.phase) {
              useStore.getState().setLastTouchpointMs(Date.now())
              api.setPhase(s.phase).then(res => {
                if (!res.ok) {
                  useStore.getState().pushToast(
                    'Phase transition rejected -- the agent may no longer be awaiting input.',
                    'warning',
                  )
                }
              }).catch(() => {
                useStore.getState().pushToast(
                  'Phase transition failed -- network error.',
                  'warning',
                )
              })
            } else {
              setChatDraft(s.command || '')
            }
          }}
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
 * The historical prop threads through to renderEntryBody for phase-scoped
 * styling (teal accents) and yield suppression.
 */
const EntryRow = React.memo(function EntryRow({ entry, historical }: { entry: ConversationEntry; historical: boolean }) {
  return renderEntryBody(entry, historical)
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
// Stable empty reference so the availablePhases subscription does not return a
// fresh [] on every render (which would loop useSyncExternalStore).
const EMPTY_PHASES: { id: string; description: string }[] = []

export function ContentStream() {
  const showFeedback = useStore(selectShowFeedback)
  const entries = useStore(selectFocusedEntries)

  // Phase header: title bar + handoff context card for the displayed phase.
  // displayedPhase is viewingPhaseId ?? phase so historical viewing reflects
  // the viewed phase, not the active one.
  const phase = useStore(selectPhase)
  const viewingPhaseId = useStore(s => s.viewingPhaseId)
  const artifacts = useStore(selectArtifacts)
  const isHistorical = viewingPhaseId !== null && viewingPhaseId !== phase
  const availablePhases = useStore(s => s.run?.availablePhases ?? EMPTY_PHASES)
  const displayedPhase = viewingPhaseId ?? phase
  // Derive the viewed phase's title, handoff artifacts, and subtitle from
  // the previous phase's artifacts (filtered by producedPhaseId).
  const { phaseTitle, isFirstPhase, prevPhaseName, handoffArtifacts, subtitle } = useMemo(() => {
    const idx = availablePhases.findIndex(p => p.id === displayedPhase)
    const prev = idx > 0 ? availablePhases[idx - 1] : null
    const prevId = prev?.id ?? null
    const handoff = prevId
      ? Object.values(artifacts)
        .filter(a => a.producedPhaseId === prevId)
        .map(a => ({ name: a.path.split('/').pop() ?? a.path, role: 'handoff' as const }))
      : []
    const subtitleText = handoff.length > 0
      ? `from ${handoff.map(a => a.name).join(', ')}`
      : undefined
    return {
      phaseTitle: displayedPhase ? formatPhaseName(displayedPhase) : '',
      isFirstPhase: idx <= 0,
      prevPhaseName: prev ? formatPhaseName(prev.id) : '',
      handoffArtifacts: handoff,
      subtitle: subtitleText,
    }
  }, [displayedPhase, availablePhases, artifacts])

  // When the active phase changes (koan_set_phase fires and run.phase updates
  // via SSE patch), reset viewingPhaseId to null so the view follows the new
  // phase. Under the null = "follow active phase" semantics, null filters
  // entries to run.phase. The ref guard ensures the reset fires only on an
  // actual phase change, NOT on ContentStream remount (which happens when an
  // elicitation or completion view temporarily unmounts ContentStream).
  const prevPhaseRef = useRef(phase)
  useEffect(() => {
    if (prevPhaseRef.current !== phase) {
      prevPhaseRef.current = phase
      useStore.getState().setViewingPhaseId(null)
    }
  }, [phase])

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
    showFeedback: showFeedback && !isHistorical,
  }

  // -------------------------------------------------------------------------

  return (
    <div className="content-column" ref={setScrollParent}>
      {isHistorical && (
        <ReturnBanner
          activePhase={formatPhaseName(phase)}
          // Null = "follow active phase" (live mode); returns to the current
          // phase's entries.
          onClick={() => useStore.getState().setViewingPhaseId(null)}
        />
      )}
      {phaseTitle && (
        <div className="cs-phase-header">
          <PhaseTitleBar
            status={isHistorical ? 'completed' : 'active'}
            name={phaseTitle}
            subtitle={isHistorical ? undefined : subtitle}
          />
          {!isFirstPhase && (
            <ContextCard fromPhase={prevPhaseName} artifacts={handoffArtifacts} />
          )}
        </div>
      )}
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
        <div className={
          paletteOpen ? 'content-stream content-stream--faded'
          : isHistorical ? 'content-stream content-stream--historical'
          : 'content-stream'
        }>
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
                <EntryRow entry={e} historical={isHistorical} />
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
