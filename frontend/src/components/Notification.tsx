// Renders both projection-synced notifications and client-only toasts.
// Server notifications are append-only; client toasts are dismissed via
// dismissToast (client-only channel that survives SSE merges).
// Data reads use shared selectors (stable references under M2 structural
// sharing). The dismissToast setter read remains inline -- action refs are stable.
import { useEffect, useState } from 'react'
import { useStore, Notification as NotificationData, ClientToast } from '../store/index'
import { selectNotifications, selectToasts } from '../store/selectors'

function NotificationItem({ entry }: { entry: NotificationData }) {
  const [fading, setFading] = useState(false)
  const [hidden, setHidden] = useState(false)

  // Server notifications are append-only — auto-dismiss after timeout via local state
  useEffect(() => {
    const fadeTimer = setTimeout(() => setFading(true), 4700)
    const hideTimer = setTimeout(() => setHidden(true), 5000)
    return () => {
      clearTimeout(fadeTimer)
      clearTimeout(hideTimer)
    }
  }, [])

  if (hidden) return null

  return (
    <div className={`notification ${entry.level}${fading ? ' fade-out' : ''}`}>
      {entry.message}
    </div>
  )
}

function ToastItem({ toast, onDismiss }: { toast: ClientToast; onDismiss: (id: number) => void }) {
  const [fading, setFading] = useState(false)
  const [hidden, setHidden] = useState(false)

  // Auto-dismiss after the same cadence as server notifications.
  useEffect(() => {
    const fadeTimer = setTimeout(() => setFading(true), 4700)
    const hideTimer = setTimeout(() => {
      setHidden(true)
      onDismiss(toast.id)
    }, 5000)
    return () => {
      clearTimeout(fadeTimer)
      clearTimeout(hideTimer)
    }
  }, [toast.id, onDismiss])

  if (hidden) return null

  return (
    <div className={`notification ${toast.level}${fading ? ' fade-out' : ''}`}>
      {toast.message}
    </div>
  )
}

/** Renders both projection notifications (append-only) and client toasts (dismissible). */
export function Notification() {
  const notifications = useStore(selectNotifications)
  const toasts = useStore(selectToasts)
  const dismissToast = useStore(s => s.dismissToast)

  return (
    <div id="notifications">
      {notifications.map((n, i) => (
        <NotificationItem key={`${n.timestampMs}-${i}`} entry={n} />
      ))}
      {toasts.map(t => (
        <ToastItem key={t.id} toast={t} onDismiss={dismissToast} />
      ))}
    </div>
  )
}
