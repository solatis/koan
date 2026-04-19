/**
 * TabBar — horizontal category switcher with underline indicator.
 *
 * Used in: settings Agents section (runner type tabs: claude, codex,
 * gemini) and future tabbed content areas.
 */

import './TabBar.css'

interface TabBarProps {
  tabs: string[]
  activeTab: string
  onChange: (tab: string) => void
}

export function TabBar({ tabs, activeTab, onChange }: TabBarProps) {
  return (
    <div className="tab-bar" role="tablist">
      {tabs.map(tab => (
        <span
          key={tab}
          role="tab"
          tabIndex={0}
          aria-selected={tab === activeTab}
          className={`tab-bar-tab${tab === activeTab ? ' tab-bar-tab--active' : ''}`}
          onClick={() => onChange(tab)}
          onKeyDown={e => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              onChange(tab)
            }
          }}
        >
          {tab}
        </span>
      ))}
    </div>
  )
}

export default TabBar
