/**
 * UsageGauge -- compact usage readout for the HeaderBar right cluster.
 *
 * Shows the primary agent's token counts, cost, and cache hit/write stats,
 * all sourced from the projection's per-agent conversation.
 * Presentational: all data arrives via props, no store access.
 *
 * Readouts (each gated on a non-zero check):
 *   tok   -- input / output token counts
 *   $     -- total accumulated cost in USD (shown when > 0)
 *   cache -- cache read / write token counts (shown when either > 0)
 *
 * Used in: HeaderBar (workflow mode), beside the orchestrator model + elapsed.
 */

import './UsageGauge.css'

interface UsageGaugeProps {
  inputTokens: number
  outputTokens: number
  cacheReadTokens: number
  cacheWriteTokens: number
  totalCostUsd: number
}

/** Compact a token count: 12345 -> "12.3k", 850 -> "850". */
function fmtTokens(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  return String(n)
}

/** Format a USD cost: 0.01234 -> "$0.0123", 1.5 -> "$1.50". */
function fmtCost(usd: number): string {
  if (usd >= 1) return `$${usd.toFixed(2)}`
  return `$${usd.toFixed(4)}`
}

export function UsageGauge({
  inputTokens,
  outputTokens,
  cacheReadTokens,
  cacheWriteTokens,
  totalCostUsd,
}: UsageGaugeProps) {
  const title =
    `${inputTokens.toLocaleString()} input tokens / ` +
    `${outputTokens.toLocaleString()} output tokens` +
    (totalCostUsd > 0 ? ` / cost ${fmtCost(totalCostUsd)}` : '') +
    ((cacheReadTokens > 0 || cacheWriteTokens > 0)
      ? ` / cache ${cacheReadTokens.toLocaleString()} read / ${cacheWriteTokens.toLocaleString()} write`
      : '')

  return (
    <span className="ug" title={title}>
      <span className="ug-label">tok</span>
      <span className="ug-val">{fmtTokens(inputTokens)} in</span>
      <span className="ug-sep">/</span>
      <span className="ug-val">{fmtTokens(outputTokens)} out</span>

      {totalCostUsd > 0 && (
        <>
          <span className="ug-divider">|</span>
          <span className="ug-label">cost</span>
          <span className="ug-cost">{fmtCost(totalCostUsd)}</span>
        </>
      )}

      {(cacheReadTokens > 0 || cacheWriteTokens > 0) && (
        <>
          <span className="ug-divider">|</span>
          <span className="ug-label">cache</span>
          <span className="ug-val">{fmtTokens(cacheReadTokens)}</span>
          <span className="ug-sep">/</span>
          <span className="ug-val">{fmtTokens(cacheWriteTokens)}</span>
        </>
      )}
    </span>
  )
}

export default UsageGauge
