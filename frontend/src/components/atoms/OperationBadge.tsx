import Badge from './Badge'

type Operation = 'add' | 'update' | 'deprecate'

const LABELS: Record<Operation, string> = {
  add: '+ Add',
  update: '~ Update',
  deprecate: '\u2212 Deprecate',
}

interface OperationBadgeProps {
  op: Operation
}

export function OperationBadge({ op }: OperationBadgeProps) {
  return <Badge variant={op}>{LABELS[op]}</Badge>
}

export default OperationBadge
