import './MemoryCurationPage.css'
import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'
import QueueStateIndicator from '../atoms/QueueStateIndicator'
import Button from '../atoms/Button'
import OperationProposalHead from '../molecules/OperationProposalHead'
import RationaleBlock from '../molecules/RationaleBlock'
import { DiffPane } from '../molecules/DiffPane'
import OverallFeedback from '../molecules/OverallFeedback'

type MemoryType = 'decision' | 'lesson' | 'context' | 'procedure'
type Op = 'add' | 'update' | 'deprecate'
type Decision = 'approved' | 'rejected'

type AddProposal = {
  id: string
  op: 'add'
  type: MemoryType
  seq: string
  title: string
  meta: string
  rationale: ReactNode
  addBody: ReactNode
  decision?: Decision
  feedback: string
}

type UpdateProposal = {
  id: string
  op: 'update'
  type: MemoryType
  seq: string
  title: string
  meta: string
  rationale: ReactNode
  updateBefore: ReactNode
  updateAfter: ReactNode
  decision?: Decision
  feedback: string
}

type DeprecateProposal = {
  id: string
  op: 'deprecate'
  type: MemoryType
  seq: string
  title: string
  meta: string
  rationale: ReactNode
  deprecateBody: ReactNode
  decision?: Decision
  feedback: string
}

type Proposal = AddProposal | UpdateProposal | DeprecateProposal

interface MemoryCurationPageProps {
  eyebrow?: string
  subtitle?: string | ReactNode
  proposals: Proposal[]
  selectedIndex: number
  onSelectIndex: (i: number) => void
  onApprove: (id: string) => void
  onReject: (id: string) => void
  onChangeDecision: (id: string) => void
  onFeedbackChange: (id: string, v: string) => void
  // Called whenever a per-decision OverallFeedback attachment list changes;
  // the caller (CurationTakeover) owns the map to include in buildDecisions().
  onProposalFileIdsChange?: (id: string, ids: string[]) => void
  onCancel: () => void
  // onSubmit is intentionally absent: submission is auto-triggered by the
  // parent (CurationTakeover) on the pending->0 edge, not by a manual button.
}

const OP_LABELS: Record<Op, string> = { add: 'Add', update: 'Update', deprecate: 'Deprecate' }

function QueueItem({ state, index, op, seq, title, active, onClick }: {
  state: 'pending' | Decision
  index: number
  op: Op
  seq: string
  title: string
  active: boolean
  onClick: () => void
}) {
  return (
    <button type="button" className={`qi${active ? ' qi--active' : ''}`} onClick={onClick}>
      <QueueStateIndicator state={state} index={index} />
      <div className="qi-body">
        <div className="qi-head">
          <span className={`qi-op qi-op--${op}`}>{OP_LABELS[op]}</span>
          <span className="qi-seq">{seq}</span>
        </div>
        <span className="qi-title">{title}</span>
      </div>
      <span className="qi-arrow">{'\u203a'}</span>
    </button>
  )
}

/**
 * CurationQueue -- left-panel sidebar listing all proposals in the batch.
 *
 * Displays the tally row, the scrollable proposal list, and the submit-area
 * footer. The primary submit affordance is implicit: CurationTakeover fires
 * auto-submit when the last pending decision is made. This component only
 * exposes Cancel, which submits a reject-all payload immediately.
 */
function CurationQueue({
  eyebrow = 'Memory curation \u00b7 post-mortem',
  subtitle,
  proposals,
  selectedIndex,
  onSelectIndex,
  pending,
  approved,
  rejected,
  onCancel,
}: {
  eyebrow?: string
  subtitle?: string | ReactNode
  proposals: Proposal[]
  selectedIndex: number
  onSelectIndex: (i: number) => void
  pending: number
  approved: number
  rejected: number
  onCancel: () => void
}) {
  const tallyCells: ReactNode[] = []
  if (approved > 0) tallyCells.push(<span key="a"><span className="cq-tally-n">{approved}</span> approved</span>)
  if (rejected > 0) tallyCells.push(<span key="r"><span className="cq-tally-n">{rejected}</span> rejected</span>)
  tallyCells.push(<span key="p"><span className="cq-tally-n">{pending}</span> pending</span>)

  return (
    <div className="cq">
      <div className="cq-card">
        <div className="cq-head">
          <div className="cq-eyebrow">{eyebrow}</div>
          <h2 className="cq-title">{proposals.length} proposals</h2>
          {subtitle && <div className="cq-subtitle">{subtitle}</div>}
        </div>
        <div className="cq-tally">
          {tallyCells.map((c, i) => (
            <span key={i}>
              {i > 0 && <span className="cq-tally-sep"> &middot; </span>}
              {c}
            </span>
          ))}
        </div>
        <div className="cq-list">
          {proposals.map((p, i) => (
            <QueueItem
              key={p.id}
              state={p.decision ?? 'pending'}
              index={i + 1}
              op={p.op}
              seq={p.seq}
              title={p.title}
              active={i === selectedIndex}
              onClick={() => onSelectIndex(i)}
            />
          ))}
        </div>
      </div>
      <div className="cq-submit">
        <div className="cq-submit-note">
          {`${pending} decision${pending !== 1 ? 's' : ''} pending. The last decision will submit the batch automatically.`}
        </div>
        <div className="cq-submit-actions">
          <Button variant="secondary" size="sm" onClick={onCancel}>Cancel</Button>
        </div>
      </div>
    </div>
  )
}

function ProposalDetailPane({
  proposal,
  position,
  onApprove,
  onReject,
  onChangeDecision,
  onFeedbackChange,
  onFileIdsChange,
}: {
  proposal: Proposal
  position: { index: number; total: number }
  onApprove: () => void
  onReject: () => void
  onChangeDecision: () => void
  onFeedbackChange: (v: string) => void
  onFileIdsChange?: (ids: string[]) => void
}) {
  const paneRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    paneRef.current?.scrollTo({ top: 0, behavior: 'auto' })
  }, [proposal.id])

  return (
    <div className="pdp" ref={paneRef}>
      <div className="pdp-top">
        <span className="pdp-position">Proposal {position.index} of {position.total}</span>
      </div>
      <div className="pdp-head">
        <OperationProposalHead
          op={proposal.op}
          type={proposal.type}
          seq={proposal.seq}
          title={proposal.title}
          decision={proposal.decision}
        />
      </div>
      <div className="pdp-meta">{proposal.meta}</div>
      <div className="pdp-rationale">
        <RationaleBlock>{proposal.rationale}</RationaleBlock>
      </div>
      <div className="pdp-body">
        {proposal.op === 'update' && (
          <DiffPane before={proposal.updateBefore} after={proposal.updateAfter} />
        )}
        {proposal.op === 'add' && (
          <div className="pdp-add-prose">{proposal.addBody}</div>
        )}
        {proposal.op === 'deprecate' && (
          <div className="pdp-deprecate-prose">{proposal.deprecateBody}</div>
        )}
      </div>
      <div className="pdp-feedback">
        <OverallFeedback
          label="Your feedback"
          placeholder="Leave empty to just approve/reject. Write feedback to revise (if rejecting) or annotate (if approving)."
          value={proposal.feedback}
          onChange={onFeedbackChange}
          onFileIdsChange={onFileIdsChange}
        />
      </div>
      <div className="pdp-actions">
        {proposal.decision && (
          <Button variant="secondary" size="sm" onClick={onChangeDecision}>Change decision</Button>
        )}
        <span className="pdp-spacer" />
        <Button variant="secondary" size="sm" onClick={onReject} disabled={proposal.decision === 'rejected'}>Reject</Button>
        <Button variant="primary" size="sm" onClick={onApprove} disabled={proposal.decision === 'approved'}>Approve</Button>
      </div>
    </div>
  )
}

/**
 * MemoryCurationPage -- two-panel memory curation layout.
 *
 * Left panel: CurationQueue (proposal list + submit area).
 * Right panel: ProposalDetailPane (decision form for the selected proposal).
 *
 * Submission is auto-triggered by the parent (CurationTakeover) on the
 * pending->0 edge; this component exposes no onSubmit prop.
 */
export function MemoryCurationPage({
  eyebrow,
  subtitle,
  proposals,
  selectedIndex,
  onSelectIndex,
  onApprove,
  onReject,
  onChangeDecision,
  onFeedbackChange,
  onProposalFileIdsChange,
  onCancel,
}: MemoryCurationPageProps) {
  const pending = proposals.filter(p => !p.decision).length
  const approved = proposals.filter(p => p.decision === 'approved').length
  const rejected = proposals.filter(p => p.decision === 'rejected').length
  const selected = proposals[selectedIndex]

  return (
    <div className="mcp-page">
      <CurationQueue
        eyebrow={eyebrow}
        subtitle={subtitle}
        proposals={proposals}
        selectedIndex={selectedIndex}
        onSelectIndex={onSelectIndex}
        pending={pending}
        approved={approved}
        rejected={rejected}
        onCancel={onCancel}
      />
      {selected && (
        <ProposalDetailPane
          proposal={selected}
          position={{ index: selectedIndex + 1, total: proposals.length }}
          onApprove={() => onApprove(selected.id)}
          onReject={() => onReject(selected.id)}
          onChangeDecision={() => onChangeDecision(selected.id)}
          onFeedbackChange={v => onFeedbackChange(selected.id, v)}
          onFileIdsChange={onProposalFileIdsChange ? ids => onProposalFileIdsChange(selected.id, ids) : undefined}
        />
      )}
    </div>
  )
}

export default MemoryCurationPage
