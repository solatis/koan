/**
 * modelConfig -- shared model-configuration helpers for run-view connected
 * wrappers (ConnectedSettingsPage, ConnectedNewRunForm).
 *
 * Lives in the connected layer so presentational components stay store-free
 * and never import these constants or helpers directly.  Extracted from
 * App.tsx in M5 to avoid duplicating the join logic in both wrappers.
 */

import type { Settings } from '../../store/index'
import type { ConnectionSummary, ModelsForConnection, RoleSlot } from './SettingsPage'
import type { ProviderType } from '../atoms/ProviderBadge'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

// Provider types that expose a live list-models endpoint.
export const LISTING_CAPABLE_TYPES = new Set(['anthropic', 'openai', 'google', 'openrouter', 'ollama-cloud'])

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

/**
 * Derive the ConnectionSummary list and modelsByConnection map consumed by
 * both ConnectedSettingsPage and ConnectedNewRunForm.  Extracted here to avoid
 * duplicating the join logic in both connected components.
 *
 * Model/family join is per-connection (by connectionId), not per provider type.
 * The static catalog (modelRegistry) is still provider-scoped since it is not
 * connection-specific.
 */
export function buildConnectionViews(
  settings: Settings,
  modelsLoading: Record<string, boolean>,
): {
  connections: ConnectionSummary[]
  modelsByConnection: Record<string, ModelsForConnection>
} {
  const statusByConn: Record<string, boolean> = {}
  for (const cs of settings.providerStatus) {
    statusByConn[cs.connectionId] = cs.available
  }

  const connections: ConnectionSummary[] = settings.connections.map(c => {
    const available = statusByConn[c.id] ?? false
    const region = c.region ? ` · ${c.region}` : ''
    const url = c.baseUrl ? ` · ${c.baseUrl}` : ''
    const keyState = available ? 'key set' : 'no key'
    return {
      type: c.connectionType as ProviderType,
      id: c.id,
      meta: `${c.connectionType}${region}${url} · ${keyState}`,
      status: available ? 'configured' : 'not-set',
      listingCapable: LISTING_CAPABLE_TYPES.has(c.connectionType),
    }
  })

  const modelsByConnection: Record<string, ModelsForConnection> = {}
  for (const conn of settings.connections) {
    // Filtered by connection id: each connection carries its own model list so
    // two connections of the same provider type do not overwrite each other.
    const live = settings.providerModels
      .filter(m => m.connectionId === conn.id)
      .map(m => m.model)
    const catalog = settings.modelRegistry
      .filter(r => r.provider === conn.connectionType)
      .map(r => r.model)
    // Families are also per-connection (connectionId on the wire).
    const rawFamilies = (settings.providerFamilies ?? []).filter(f => f.connectionId === conn.id)
    const families = rawFamilies.map(f => ({ family: f.family, resolved: f.resolved }))
    // For voyage connections, catalog suggestions come from the static Voyage
    // embedding model catalog (embeddingModels), not the general model registry.
    const voyageSuggestions = conn.connectionType === 'voyage'
      ? (settings.embeddingModels ?? []).map(e => e.modelId)
      : undefined
    modelsByConnection[conn.id] = {
      models: live.length > 0 ? live : catalog,
      loading: modelsLoading[conn.id] ?? false,
      catalogSuggestions: conn.connectionType === 'voyage'
        ? voyageSuggestions
        : (LISTING_CAPABLE_TYPES.has(conn.connectionType) ? undefined : catalog),
      families: families.length > 0 ? families : undefined,
    }
  }
  return { connections, modelsByConnection }
}

// ---------------------------------------------------------------------------
// slotToMemoryKind
// ---------------------------------------------------------------------------

// Map UI slot names to API memory kind strings.
export function slotToMemoryKind(slot: RoleSlot): string {
  if (slot === 'memory-llm') return 'memory_llm'
  if (slot === 'reflect-llm') return 'reflect_llm'
  return slot  // 'embedding'
}
