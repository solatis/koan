// Fixed top bar: logo · PillStrip · settings button.
//
// PillStrip reads phase from the store to render pipeline progress pills.
// The settings button toggles showSettings, which flips App into interactive
// mode and renders ModelConfig over the current phase content.

import { PillStrip } from './PillStrip.jsx'
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
      </div>
    </header>
  )
}
