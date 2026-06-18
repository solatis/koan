/**
 * ConnectedSidebar -- store connector for the run-view artifacts sidebar.
 *
 * Reads artifacts, reviewing-artifact state, and the last touchpoint timestamp
 * via narrow shared selectors so this component re-renders only when those
 * slices change.  The Date.now()-based modifiedAgo derivation stays in the
 * in-component useMemo because it is inherently time-relative and cannot be
 * captured in a pure reselect selector.
 *
 * Moved from App.tsx to this module in M5.
 */

import { useMemo } from 'react'
import { useStore } from '../../store/index'
import { selectArtifacts, selectReviewingArtifact, selectLastTouchpointMs } from '../../store/selectors'
import { ArtifactsSidebar } from './ArtifactsSidebar'

export function ConnectedSidebar() {
  const artifacts = useStore(selectArtifacts)
  const reviewingArtifact = useStore(selectReviewingArtifact)
  const setReviewingArtifact = useStore(s => s.setReviewingArtifact)
  // lastTouchpointMs is null until the first yield resolves; all artifacts show
  // as "changed" in that initial state, which is the intended behaviour.
  const lastTouchpointMs = useStore(selectLastTouchpointMs)

  const entries = useMemo(() => {
    const now = Date.now()
    const list = Object.values(artifacts).map(a => {
      const mins = Math.floor((now - a.modifiedAt) / 60000)
      return {
        path: a.path,
        filename: a.path.split('/').pop() || a.path,
        modifiedAgo: mins < 1 ? 'just now' : mins < 60 ? `modified ${mins}m ago` : `modified ${Math.floor(mins / 60)}h ago`,
        variant: mins < 5 ? ('recent' as const) : ('stable' as const),
        changed: a.modifiedAt > (lastTouchpointMs ?? 0),
        _ts: a.modifiedAt,
      }
    })
    list.sort((a, b) => b._ts - a._ts)
    return list.map(({ path, filename, modifiedAgo, variant, changed }) => ({ path, filename, modifiedAgo, variant, changed }))
  }, [artifacts, lastTouchpointMs])

  const handleClick = (path: string) => {
    setReviewingArtifact(reviewingArtifact === path ? null : path)
  }

  return <ArtifactsSidebar artifacts={entries} activePath={reviewingArtifact} onArtifactClick={handleClick} />
}
