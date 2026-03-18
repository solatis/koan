import { PillStrip } from './PillStrip.jsx'
import { Timer } from './Timer.jsx'
import { useStore } from '../store.js'

export function Header() {
  return (
    <header class="header">
      <div class="header-left">
        <span class="logo">koan</span>
        <PillStrip />
      </div>
      <div class="header-right">
        <button
          class="settings-btn"
          onClick={() => useStore.setState(s => ({ showSettings: !s.showSettings }))}
          title="Model configuration"
        >
          ⚙
        </button>
        <Timer />
      </div>
    </header>
  )
}
