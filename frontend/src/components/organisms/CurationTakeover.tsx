/**
 * CurationTakeover -- full-page curation UI for koan_memory_propose.
 *
 * Rendered by App.tsx when run.activeCurationBatch is non-null, superseding
 * all other run-scoped views. Submits decisions to /api/memory/curation which
 * resolves the orchestrator's blocked future.
 *
 * The batch auto-submits the moment the last pending proposal is decided --
 * no manual Submit button. Cancel submits a reject-all payload immediately.
 *
 * Per-proposal decision/feedback draft is store-only (accept-loss: cleared
 * when the batch clears). Batch data itself is server-backed and survives
 * a page refresh.
 */

import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'

import { useStore } from '../../store/index'
import type { Proposal, ActiveCurationBatch } from '../../store/index'
import { Md } from '../Md'
import * as api from '../../api/client'

import { MemoryCurationPage } from './MemoryCurationPage'

// ---------------------------------------------------------------------------
// Proposal shape mapping
// ---------------------------------------------------------------------------

// Map wire Proposal to the discriminated union expected by MemoryCurationPage.
function mapProposal(p: Proposal, d: { decision?: 'approved' | 'rejected'; feedback: string }) {
  const common = {
    id: p.id,
    type: p.type,
    seq: p.seq,
    title: p.title,
    meta: p.meta,
    rationale: <Md>{p.rationale}</Md> as ReactNode,
    decision: d.decision,
    feedback: d.feedback,
  }
  if (p.op === 'add') {
    return { ...common, op: 'add' as const, addBody: <Md>{p.body ?? ''}</Md> as ReactNode }
  }
  if (p.op === 'update') {
    return {
      ...common,
      op: 'update' as const,
      updateBefore: <Md>{p.before ?? ''}</Md> as ReactNode,
      updateAfter: <Md>{p.after ?? ''}</Md> as ReactNode,
    }
  }
  // deprecate
  return { ...common, op: 'deprecate' as const, deprecateBody: <Md>{p.body ?? ''}</Md> as ReactNode }
}

// ---------------------------------------------------------------------------
// CurationTakeover component
// ---------------------------------------------------------------------------

export function CurationTakeover() {
  const batch = useStore(s => s.run?.activeCurationBatch) as ActiveCurationBatch
  const draft = useStore(s => s.memoryCurationDraft)
  const setDecision = useStore(s => s.setMemoryCurationDecision)
  const setFeedback = useStore(s => s.setMemoryCurationFeedback)
  const resetDraft = useStore(s => s.resetMemoryCurationDraft)
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [submitting, setSubmitting] = useState(false)
  // Per-proposal attachment IDs, keyed by proposal_id. Owned here rather than
  // inside MemoryCurationPage so buildDecisions() can access the full map.
  const [decisionFileIds, setDecisionFileIds] = useState<Record<string, string[]>>({})

  // Seed the draft when the batch mounts or changes.
  useEffect(() => {
    resetDraft(batch)
    setSelectedIndex(0)
  }, [batch?.batchId])

  if (!batch) return null

  const proposals = batch.proposals.map(p => mapProposal(p, draft[p.id] ?? { feedback: '' }))

  /**
   * Build the CurationDecision payload for every proposal in the batch.
   *
   * `override` lets the auto-submit path inject the just-decided value for one
   * proposal without waiting for a React re-render: the `draft` closure captured
   * by this function is the pre-update snapshot, so reading `draft[id]` after
   * calling `setDecision(id, ...)` would still return the old value. Passing an
   * override avoids that race without requiring an imperative store read.
   */
  const buildDecisions = (
    override?: { id: string; decision: 'approved' | 'rejected' }
  ): api.CurationDecision[] =>
    batch.proposals.map(p => {
      const d = draft[p.id] ?? {}
      const ids = decisionFileIds[p.id] ?? []
      const decision: 'approved' | 'rejected' =
        override && override.id === p.id
          ? override.decision
          : (d.decision ?? 'rejected')
      const entry: api.CurationDecision = {
        proposal_id: p.id,
        decision,
        feedback: d.feedback ?? '',
      }
      if (ids.length > 0) entry.attachments = ids
      return entry
    })

  /**
   * Submit a fully-built decisions payload. Owns the `submitting` re-entry
   * guard so that auto-submit and cancel share identical transport semantics.
   * Callers are responsible for building the payload before calling this
   * (auto-submit: via buildDecisions({id, decision}); cancel: inline reject-all).
   */
  const submitWithDecisions = async (decisions: api.CurationDecision[]) => {
    if (submitting) return
    setSubmitting(true)
    await api.submitMemoryCuration(batch.batchId, decisions).catch(() => {})
    setSubmitting(false)
  }

  // Advance to the next proposal after Approve / Reject so the user can
  // work through a batch without manually clicking each row. Capped at the
  // last index so it never wraps or goes out of bounds. Functional updater
  // avoids stale-closure bugs when React batches clicks during a render.
  const advanceSelection = () => {
    setSelectedIndex(i => Math.min(i + 1, proposals.length - 1))
  }

  /**
   * Cancel = reject all with no feedback or attachments, submitted immediately.
   * Thin wrapper around submitWithDecisions with an inline reject-all payload.
   */
  const handleCancel = async () => {
    const decisions = batch.proposals.map(p => ({
      proposal_id: p.id,
      decision: 'rejected' as const,
      feedback: '',
    }))
    await submitWithDecisions(decisions)
  }

  /**
   * Returns true iff every proposal OTHER than `clickedId` already has a
   * decision in the current draft snapshot. When true, the click that just
   * landed is the one that takes pending from 1 to 0, so auto-submit must fire.
   *
   * Reads the pre-update `draft` snapshot deliberately: `setDecision` will
   * have been called on `clickedId` just before this check, but the closure
   * here still holds the old map -- so we exclude `clickedId` from the check.
   */
  const isLastPending = (clickedId: string): boolean =>
    batch.proposals.every(p =>
      p.id === clickedId ? true : Boolean(draft[p.id]?.decision)
    )

  /**
   * Handle an Approve or Reject click. Two branches:
   * - If this is the last pending proposal (pending 1 -> 0): auto-submit with
   *   an override so the payload includes the just-decided value before React
   *   re-renders. advanceSelection is intentionally skipped -- the takeover
   *   is about to unmount.
   * - Otherwise: record the decision and advance the selection cursor so the
   *   user can move through the batch without manual navigation.
   */
  const handleDecide = (id: string, decision: 'approved' | 'rejected') => {
    setDecision(id, decision)
    if (isLastPending(id)) {
      void submitWithDecisions(buildDecisions({ id, decision }))
      return
    }
    advanceSelection()
  }

  return (
    <MemoryCurationPage
      proposals={proposals}
      selectedIndex={selectedIndex}
      onSelectIndex={setSelectedIndex}
      onApprove={id => handleDecide(id, 'approved')}
      onReject={id => handleDecide(id, 'rejected')}
      onChangeDecision={id => setDecision(id, undefined)}
      onFeedbackChange={(id, v) => setFeedback(id, v)}
      onProposalFileIdsChange={(id, ids) => setDecisionFileIds(prev => ({ ...prev, [id]: ids }))}
      onCancel={handleCancel}
    />
  )
}
