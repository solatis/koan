/**
 * CurationTakeover -- full-page curation UI for koan_memory_propose.
 *
 * Rendered by App.tsx when run.activeCurationBatch is non-null, superseding
 * all other run-scoped views. Submits decisions to /api/memory/curation which
 * resolves the orchestrator's blocked future.
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

  const buildDecisions = (): api.CurationDecision[] =>
    batch.proposals.map(p => {
      const d = draft[p.id] ?? {}
      const ids = decisionFileIds[p.id] ?? []
      const entry: api.CurationDecision = {
        proposal_id: p.id,
        decision: d.decision ?? 'rejected',
        feedback: d.feedback ?? '',
      }
      if (ids.length > 0) entry.attachments = ids
      return entry
    })

  const handleSubmit = async () => {
    if (submitting) return
    setSubmitting(true)
    await api.submitMemoryCuration(batch.batchId, buildDecisions()).catch(() => {})
    setSubmitting(false)
  }

  // Advance to the next proposal after Approve / Reject so the user can
  // work through a batch without manually clicking each row. Capped at the
  // last index so it never wraps or goes out of bounds. Functional updater
  // avoids stale-closure bugs when React batches clicks during a render.
  const advanceSelection = () => {
    setSelectedIndex(i => Math.min(i + 1, proposals.length - 1))
  }

  const handleCancel = async () => {
    if (submitting) return
    setSubmitting(true)
    // Cancel = reject all with no feedback.
    const decisions = batch.proposals.map(p => ({
      proposal_id: p.id,
      decision: 'rejected' as const,
      feedback: '',
    }))
    await api.submitMemoryCuration(batch.batchId, decisions).catch(() => {})
    setSubmitting(false)
  }

  return (
    <MemoryCurationPage
      proposals={proposals}
      selectedIndex={selectedIndex}
      onSelectIndex={setSelectedIndex}
      onApprove={id => { setDecision(id, 'approved'); advanceSelection() }}
      onReject={id => { setDecision(id, 'rejected'); advanceSelection() }}
      onChangeDecision={id => setDecision(id, undefined)}
      onFeedbackChange={(id, v) => setFeedback(id, v)}
      onProposalFileIdsChange={(id, ids) => setDecisionFileIds(prev => ({ ...prev, [id]: ids }))}
      onSubmit={handleSubmit}
      onCancel={handleCancel}
    />
  )
}
