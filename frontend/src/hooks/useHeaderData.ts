/**
 * useHeaderData -- derives all props consumed by HeaderBar from the store.
 *
 * Reads via shared selectors (selectPhase, selectPrimaryAgent) rather than
 * subscribing to s.run or s.run.agents by reference, so re-renders are
 * bounded to patches that actually touch the phase or agents.  The elapsed
 * counter still uses Date.now() and re-renders on the useElapsed tick, which
 * is expected -- it is a time-display hook by nature.
 *
 * Moved from App.tsx to this module in M5.
 */

import { useMemo } from 'react'
import { useStore } from '../store/index'
import { selectPhase, selectPrimaryAgent } from '../store/selectors'
import { useElapsed } from './useElapsed'

export function useHeaderData() {
  // Narrow subscriptions: only re-render when phase or primary agent changes.
  const phase = useStore(selectPhase)
  const primary = useStore(selectPrimaryAgent)

  const lastStep = useMemo(() => {
    if (!primary) return null
    for (let i = primary.conversation.entries.length - 1; i >= 0; i--) {
      const e = primary.conversation.entries[i]
      if (e.type === 'step') return e
    }
    return null
  }, [primary])

  const elapsed = useElapsed(primary?.startedAtMs ?? Date.now())

  return {
    phase: phase ? phase.split('-').map(w => w[0].toUpperCase() + w.slice(1)).join(' ') : '',
    step: lastStep?.stepName ?? primary?.stepName ?? '',
    totalSteps: lastStep?.totalSteps ?? 0,
    currentStep: lastStep?.step ?? 0,
    orchestratorModel: primary?.model ?? undefined,
    elapsed: primary ? elapsed : undefined,
    usage: primary
      ? {
          inputTokens: primary.conversation.inputTokens,
          outputTokens: primary.conversation.outputTokens,
          cacheReadTokens: primary.conversation.cacheReadTokens,
          cacheWriteTokens: primary.conversation.cacheWriteTokens,
          totalCostUsd: primary.conversation.totalCostUsd,
        }
      : undefined,
  }
}
