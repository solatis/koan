/**
 * EntityRow — two-line list item for configuration entities.
 *
 * Used in: settings Profiles section (profile rows), settings Agents
 * section (installation rows). Displays a name, optional badges,
 * optional action buttons, and a metadata subtitle line.
 *
 * The `children` slot receives inline content for the top line: badges
 * and action buttons. The parent composes these directly rather than
 * EntityRow accepting badge/action arrays — this keeps the component
 * simple and flexible.
 */

import type { ReactNode } from 'react'
import './EntityRow.css'

interface EntityRowProps {
  name: string
  mono?: boolean
  meta?: string
  active?: boolean
  children?: ReactNode
}

export function EntityRow({ name, mono = false, meta, active = false, children }: EntityRowProps) {
  const cls = [
    'entity-row',
    active && 'entity-row--active',
    mono && 'entity-row--mono',
  ].filter(Boolean).join(' ')

  return (
    <div className={cls}>
      <div className="entity-row-top">
        <span className="entity-row-name">{name}</span>
        {children}
      </div>
      {meta && <div className="entity-row-meta">{meta}</div>}
    </div>
  )
}

export default EntityRow
