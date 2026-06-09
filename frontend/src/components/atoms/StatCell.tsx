import './StatCell.css'

interface StatCellProps {
  value: string
  label: string
  size?: 'lg' | 'sm'
}

export function StatCell({ value, label, size = 'lg' }: StatCellProps) {
  return (
    <div className={`atom-stat-cell atom-stat-cell--${size}`}>
      <span className="atom-stat-cell__value">{value}</span>
      <span className="atom-stat-cell__label">{label}</span>
    </div>
  )
}

export default StatCell
