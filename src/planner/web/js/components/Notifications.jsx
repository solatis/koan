import { useEffect } from 'preact/hooks'
import { useStore } from '../store.js'

export function Notifications() {
  const notifications = useStore(s => s.notifications)

  useEffect(() => {
    if (notifications.length === 0) return
    const newest = notifications[notifications.length - 1]
    const timer = setTimeout(() => {
      useStore.setState(s => ({
        notifications: s.notifications.filter(n => n.id !== newest.id),
      }))
    }, 5000)
    return () => clearTimeout(timer)
  }, [notifications[notifications.length - 1]?.id])

  return (
    <div id="notifications">
      {notifications.map(n => (
        <div key={n.id} class={`notification ${n.level}`}>{n.message}</div>
      ))}
    </div>
  )
}
