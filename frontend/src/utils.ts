export function formatTokens(sent: number, recv: number): string {
  const fmt = (n: number) => {
    if (!n) return '--'
    if (n < 1000) return String(n)
    return Math.round(n / 1000) + 'k'
  }
  return `${fmt(sent)} / ${fmt(recv)}`
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

// M5: tierSummary removed -- only used by the deleted Profiles card.

// Normalize raw question options from LLM output. Options may arrive as
// strings or dicts with varying key names.
export function normalizeOptions(
  rawOpts: (string | Record<string, unknown>)[] | undefined,
): { value: string; label: string; recommended?: boolean }[] {
  if (!rawOpts) return []
  return rawOpts.map(o => {
    if (typeof o === 'string') return { value: o, label: o }
    const label = String(o['label'] ?? o['text'] ?? o['value'] ?? o['option'] ?? '')
    const value = String(o['value'] ?? o['label'] ?? o['text'] ?? label)
    return { value, label, recommended: (o['recommended'] as boolean) ?? false }
  })
}
