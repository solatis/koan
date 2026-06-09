import './OperationProposalHead.css'
import OperationBadge from '../atoms/OperationBadge'
import MemoryTypeBadge from '../atoms/MemoryTypeBadge'
import DecisionPill from './DecisionPill'

type Op = 'add' | 'update' | 'deprecate'
type MemoryType = 'decision' | 'lesson' | 'context' | 'procedure'

interface OperationProposalHeadProps {
  op: Op
  type: MemoryType
  seq: string
  title: string
  decision?: 'approved' | 'rejected'
}

export function OperationProposalHead({ op, type, seq, title, decision }: OperationProposalHeadProps) {
  return (
    <div>
      <div className="oph-meta">
        <OperationBadge op={op} />
        <MemoryTypeBadge type={type} />
        <span className="oph-seq">{seq}</span>
        {decision && <span className="oph-decision"><DecisionPill state={decision} /></span>}
      </div>
      <h2 className="oph-title">{title}</h2>
    </div>
  )
}

export default OperationProposalHead
