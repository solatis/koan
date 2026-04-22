import { Fragment } from 'react'
import './StatStrip.css'
import StatCell from '../atoms/StatCell'

interface StatStripProps {
  cells: { value: string; label: string }[]
  size?: 'lg' | 'sm'
  dividers?: boolean
}

export function StatStrip({ cells, size = 'lg', dividers = false }: StatStripProps) {
  const showDividers = dividers && size === 'lg'
  return (
    <div className={`ss ss--${size}`}>
      {cells.map((c, i) => (
        <Fragment key={i}>
          {showDividers && i > 0 && <span className="ss-divider" />}
          <StatCell value={c.value} label={c.label} size={size} />
        </Fragment>
      ))}
    </div>
  )
}

export default StatStrip
