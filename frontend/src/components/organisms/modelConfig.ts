/**
 * modelConfig -- shared model-configuration helpers for run-view connected
 * wrappers (ConnectedSettingsPage, ConnectedNewRunForm).
 *
 * Lives in the connected layer so presentational components stay store-free
 * and never import these constants or helpers directly.  Extracted from
 * App.tsx in M5 to avoid duplicating the join logic in both wrappers.
 */

import type { Settings, OfferingInfo } from '../../store/index'
import type { ConnectionSummary, ModelsForConnection, RoleSlot } from './SettingsPage'
import type { ProviderType } from '../atoms/ProviderBadge'

// Route ids whose connections expose a live list-models endpoint (Test button).
// Local (not exported): only buildConnectionViews uses it to set
// ConnectionSummary.listingCapable for the Settings Test-button gate.
const LISTING_CAPABLE: ReadonlySet<string> = new Set([
  'anthropic', 'openai', 'google', 'openrouter', 'ollama-cloud',
])

// Thinking display map -- connected layer only, so presentational components
// stay store-free.  Maps backend wire tokens to the unified display scale:
// 'disabled' shows as 'off'; low/medium/high are identity.  The wire value
// sent on change is always the native token, never the display label.
export const THINKING_DISPLAY: Record<string, string> = { disabled: 'off' }

// ---------------------------------------------------------------------------
// toThinkingOptions
// ---------------------------------------------------------------------------

/**
 * Convert a raw list of backend thinking mode tokens into {value, label} pairs
 * for use in a Select.  Prepends 'disabled' when absent (preserving existing
 * behavior -- every model gets an explicit off option).  Display label comes
 * from THINKING_DISPLAY; unrecognised tokens pass through as-is.
 *
 * Lives in the connected layer so presentational components receive typed pairs
 * and never import THINKING_DISPLAY or the store directly.
 */
export function toThinkingOptions(rawModes: string[]): { value: string; label: string }[] {
  const modes = rawModes.includes('disabled') ? rawModes : ['disabled', ...rawModes]
  return modes.map(m => ({ value: m, label: THINKING_DISPLAY[m] ?? m }))
}

// ---------------------------------------------------------------------------
// buildConnectionViews
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// versionKey / deriveFamilies
// ---------------------------------------------------------------------------

/**
 * Extract numeric version segments from a version string for sort ordering.
 * Splits on `.` and `-`, keeps digit tokens <=5 digits, returns a number
 * array. Mirrors koan.models.identity.version_key for frontend family-pin
 * derivation.
 */
function versionKey(version: string): number[] {
  return version.replace(/[.-]/g, '-')
    .split('-')
    .filter(t => /^\d{1,5}$/.test(t))
    .map(Number)
}

/**
 * Derive newest-in-family pins from a connection's offerings by grouping
 * on identity.family and picking the newest by versionKey. Returns
 * {family, resolved}[] where resolved is the wireId of the newest offering.
 */
export function deriveFamilies(offerings: OfferingInfo[]): { family: string; resolved: string }[] {
  const byFamily: Record<string, OfferingInfo[]> = {}
  for (const o of offerings) {
    if (o.identity) {
      const f = o.identity.family
      ;(byFamily[f] ??= []).push(o)
    }
  }
  return Object.entries(byFamily).map(([family, items]) => {
    const sorted = items.sort((a, b) => {
      const ka = versionKey(a.identity.version)
      const kb = versionKey(b.identity.version)
      for (let i = 0; i < Math.max(ka.length, kb.length); i++) {
        const av = ka[i] ?? -1
        const bv = kb[i] ?? -1
        if (bv !== av) return bv - av
      }
      return 0
    })
    return { family, resolved: sorted[0].wireId }
  })
}

// ---------------------------------------------------------------------------
// buildConnectionViews
// ---------------------------------------------------------------------------

/**
 * Derive the ConnectionSummary list and modelsByConnection map from the
 * settings_listed payload. Picker content comes entirely from
 * offeringsByConnection (curated catalog rendered through each connection's
 * route codec). Family pins are derived from offering identity data.
 *
 * @param settings - The store Settings object (from settings_listed snapshot).
 */
export function buildConnectionViews(
  settings: Settings,
): {
  connections: ConnectionSummary[]
  modelsByConnection: Record<string, ModelsForConnection>
} {
  const connections: ConnectionSummary[] = settings.connections.map(c => {
    const locality = c.locality ? ` · ${c.locality}` : ''
    const keyState = c.available ? 'key set' : 'no key'
    return {
      type: c.route as ProviderType,
      id: c.id,
      meta: `${c.route}${locality} · ${keyState}`,
      status: c.available ? 'configured' : 'not-set',
      listingCapable: LISTING_CAPABLE.has(c.route),
    }
  })

  const modelsByConnection: Record<string, ModelsForConnection> = {}
  for (const conn of settings.connections) {
    const offerings = settings.offeringsByConnection[conn.id] ?? []
    const families = deriveFamilies(offerings)
    modelsByConnection[conn.id] = {
      models: offerings.map(o => o.wireId),
      families: families.length > 0 ? families : undefined,
    }
  }
  return { connections, modelsByConnection }
}

// ---------------------------------------------------------------------------
// slotToMemoryKind
// ---------------------------------------------------------------------------

// Map UI slot names to API memory kind strings.
// Now only 'embedding' maps to a memory kind; 'memory-llm' and 'reflect-llm' were removed.
export function slotToMemoryKind(slot: RoleSlot): string {
  return slot  // 'embedding'
}
