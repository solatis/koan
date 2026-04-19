/**
 * FormRow — label + control(s) horizontal layout for inline forms.
 *
 * Used in: InlineForm (profile create/edit, installation create/edit).
 * Contains a fixed-width right-aligned uppercase label and a flexible
 * controls area that holds one or more TextInput, Select, or Button atoms.
 */

import type { ReactNode } from 'react'
import './FormRow.css'

interface FormRowProps {
  label: string
  children: ReactNode
}

export function FormRow({ label, children }: FormRowProps) {
  return (
    <div className="form-row">
      <span className="form-row-label">{label}</span>
      <div className="form-row-controls">
        {children}
      </div>
    </div>
  )
}

export default FormRow
