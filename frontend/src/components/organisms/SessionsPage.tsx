import { useState, useEffect } from 'react'
import * as api from '../../api/client'
import { Button } from '../atoms/Button'
import './SessionsPage.css'

// -- Helpers ------------------------------------------------------------------

function formatDate(ts: number): string {
  return new Date(ts * 1000).toLocaleString()
}

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n) + '...' : s
}

// -- Component ----------------------------------------------------------------

export function SessionsPage() {
  const [sessions, setSessions] = useState<api.Session[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  // run_id of the row currently awaiting delete confirmation, or null
  const [confirmingDelete, setConfirmingDelete] = useState<string | null>(null)

  useEffect(() => {
    api.listSessions()
      .then(r => setSessions(r.sessions))
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false))
  }, [])

  function handleDeleteRequest(run_id: string) {
    setConfirmingDelete(run_id)
  }

  function handleDeleteCancel() {
    setConfirmingDelete(null)
  }

  async function handleDeleteConfirm(run_id: string) {
    // Optimistically remove the row and reset confirmation state.
    setSessions(prev => prev.filter(s => s.run_id !== run_id))
    setConfirmingDelete(null)
    try {
      await api.deleteSession(run_id)
    } catch {
      // On failure re-fetch to restore accurate list state.
      try {
        const r = await api.listSessions()
        setSessions(r.sessions)
      } catch {
        // If re-fetch also fails, leave the optimistic state in place.
      }
    }
  }

  if (loading) {
    return <div className="loading-center">Loading...</div>
  }

  if (error) {
    return <div className="sessions-error">{error}</div>
  }

  if (sessions.length === 0) {
    return <div className="sessions-empty">No previous sessions.</div>
  }

  return (
    <div className="sessions-list">
      {sessions.map(s => (
        <div key={s.run_id} className="session-row">
          <div className="session-row-meta">
            {s.project_dir || '-'} &middot; {formatDate(s.created_at)}
          </div>
          <div className="session-row-preview">
            {truncate(s.task, 120)}
          </div>
          <div className="session-row-actions">
            {confirmingDelete === s.run_id ? (
              <>
                <span className="session-row-confirm-label">Confirm?</span>
                <Button
                  variant="danger"
                  size="sm"
                  onClick={() => handleDeleteConfirm(s.run_id)}
                >
                  Yes, delete
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={handleDeleteCancel}
                >
                  Cancel
                </Button>
              </>
            ) : (
              <>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled
                  title="Not yet implemented"
                >
                  Resume
                </Button>
                <Button
                  variant="danger"
                  size="sm"
                  onClick={() => handleDeleteRequest(s.run_id)}
                >
                  Delete
                </Button>
              </>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}
