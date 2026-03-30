import { useMemo } from 'react'
import { useStore, ArtifactFile, ALL_PHASES } from './index'

// Subscribe to the raw scouts Record -- reference-stable until setScouts is called.
// Derive the array in the component via useMemo to avoid creating a new array
// on every render (which would trigger useSyncExternalStore's infinite loop).
export function useScoutList() {
  const scouts = useStore(s => s.scouts)
  return useMemo(() => Object.values(scouts), [scouts])
}

// Isolated subscription: StatusSidebar re-renders only when primaryAgent changes.
export const usePrimaryAgent = () => useStore(s => s.primaryAgent)

// Boolean subscription: drives conditional rendering of the interaction overlay
// without subscribing to the full interaction payload.
export const useHasInteraction = () => useStore(s => s.activeInteraction !== null)

// Derive done phases from current phase -- frontend-only derivation.
export function useDonePhases(): string[] {
  const phase = useStore(s => s.phase)
  return useMemo(() => {
    const idx = ALL_PHASES.indexOf(phase)
    return idx === -1 ? [...ALL_PHASES] : ALL_PHASES.slice(0, idx)
  }, [phase])
}

function groupByDirectory(artifacts: ArtifactFile[]): Record<string, ArtifactFile[]> {
  const tree: Record<string, ArtifactFile[]> = {}
  for (const a of artifacts) {
    const parts = a.path.split('/')
    const dir = parts.length > 1 ? parts.slice(0, -1).join('/') : 'epic-root'
    if (!tree[dir]) tree[dir] = []
    tree[dir].push(a)
  }
  return tree
}

// Subscribe to the artifacts Record -- derive the tree in useMemo.
export function useArtifactTree() {
  const artifacts = useStore(s => s.artifacts)
  return useMemo(() => groupByDirectory(Object.values(artifacts)), [artifacts])
}
