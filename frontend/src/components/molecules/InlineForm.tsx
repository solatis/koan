/**
 * InlineForm — expandable edit/create region for settings entity lists.
 *
 * Used in: settings Profiles section (create/edit profile), settings
 * Agents section (create/edit installation). Appears inline below
 * entity rows within a settings section card.
 *
 * The orange border signals "user input expected here" — the same
 * semantic as the Decision panel's orange top border in elicitation
 * and the selected-state border on RadioOption/CheckboxOption.
 *
 * InlineForm is the only place in configuration UI where explicit
 * Cancel/Save buttons appear. All standalone controls auto-save.
 */

import type { ReactNode } from 'react'
import { Button } from '../atoms/Button'
import './InlineForm.css'

interface InlineFormProps {
  children: ReactNode
  onSave: () => void
  onCancel: () => void
  saving?: boolean
}

export function InlineForm({ children, onSave, onCancel, saving = false }: InlineFormProps) {
  return (
    <div className="inline-form">
      {children}
      <div className="inline-form-actions">
        <Button variant="secondary" size="sm" onClick={onCancel} disabled={saving}>
          Cancel
        </Button>
        <Button variant="primary" size="sm" onClick={onSave} disabled={saving}>
          {saving ? 'Saving...' : 'Save'}
        </Button>
      </div>
    </div>
  )
}

export default InlineForm
