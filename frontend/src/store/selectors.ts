import { useMemo } from 'react'
import { useStore, ArtifactInfo } from './index'

// Derive artifact tree grouped by directory
function groupByDirectory(artifacts: ArtifactInfo[]): Record<string, ArtifactInfo[]> {
  const tree: Record<string, ArtifactInfo[]> = {}
  for (const a of artifacts) {
    const parts = a.path.split('/')
    const dir = parts.length > 1 ? parts.slice(0, -1).join('/') : 'run-root'
    if (!tree[dir]) tree[dir] = []
    tree[dir].push(a)
  }
  return tree
}

// Subscribe to run.artifacts — derive the tree in useMemo to avoid recreating
// the array on every render (which would trigger useSyncExternalStore loops).
export function useArtifactTree() {
  const artifacts = useStore(s => s.run?.artifacts ?? {})
  return useMemo(() => groupByDirectory(Object.values(artifacts)), [artifacts])
}
