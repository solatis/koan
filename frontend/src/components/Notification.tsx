import { useEffect, useState } from 'react'
import { useStore, Notification as NotificationData } from '../store/index'

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

export function Notification() {
  const notifications = useStore(s => s.notifications)

  return (
    <div id="notifications">
      {notifications.map((n, i) => (
        <NotificationItem key={`${n.timestampMs}-${i}`} entry={n} />
      ))}
    </div>
  )
}
